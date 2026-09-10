// The two calls the app makes, plus an offline mode that serves the captured
// responses in src/fixtures. With fixtures on, a rendering bug is unambiguously
// a rendering bug: the data came out of the real server.
//
//   VITE_USE_FIXTURES=true npm run dev
//   VITE_FIXTURE_DELAY=8000 npm run dev   (to sit in the loading state)

const USE_FIXTURES = import.meta.env.VITE_USE_FIXTURES === 'true'
// Empty in development, where vite proxies /api to the local server. In a
// build it is the deployed API's origin, because the two are no longer served
// from the same host. Trailing slashes are trimmed so that setting it to
// "https://x.onrender.com/" does not produce "//api/audit".
const API_BASE = (import.meta.env.VITE_API_BASE ?? '').replace(/\/+$/, '')
const FIXTURE_DELAY = Number(import.meta.env.VITE_FIXTURE_DELAY ?? 400)

// Kept as dynamic imports so the JSON never reaches the production bundle.
const FIXTURES = {
  profile_churn: () => import('./fixtures/profile_churn.json'),
  audit_churn: () => import('./fixtures/audit_churn.json'),
  audit_reviews: () => import('./fixtures/audit_reviews.json'),
  audit_no_label: () => import('./fixtures/audit_no_label.json'),
}

// Gzipping the upload is no longer the difference between a file being refused
// and audited, now that the API is not behind a 4.5MB serverless body limit. It
// is kept because a large CSV compresses about five to one and the upload is
// the slowest part of the round trip. Below the threshold the saving is not
// worth a pass over the string.
const COMPRESS_ABOVE = 256 * 1024

export class ApiError extends Error {
  constructor(message, status) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

async function fromFixture(name) {
  const load = FIXTURES[name]
  if (!load) throw new ApiError(`No fixture named ${name}`, 0)
  await new Promise((resolve) => setTimeout(resolve, FIXTURE_DELAY))
  const module = await load()
  return module.default
}

async function gzip(text) {
  // CompressionStream is in every browser this app runs in, but a missing one
  // should cost a large file rather than every file, so the caller falls back
  // to sending the string as it is.
  if (typeof CompressionStream === 'undefined') return null
  try {
    const stream = new Blob([text]).stream().pipeThrough(new CompressionStream('gzip'))
    return new Uint8Array(await new Response(stream).arrayBuffer())
  } catch {
    return null
  }
}

async function encodeBody(body) {
  const text = JSON.stringify(body)
  const raw = new Blob([text]).size
  if (raw < COMPRESS_ABOVE) return { body: text, bytes: raw, headers: {} }
  const packed = await gzip(text)
  if (!packed || packed.byteLength >= raw) return { body: text, bytes: raw, headers: {} }
  return { body: packed, bytes: packed.byteLength, headers: { 'X-Sift-Compression': 'gzip' } }
}

async function post(path, body) {
  // Serialised before the try, so a bad payload cannot masquerade as the network
  // being down. That exact confusion cost an afternoon once.
  const payload = await encodeBody(body)

  let response
  try {
    response = await fetch(API_BASE + path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...payload.headers },
      body: payload.body,
    })
  } catch {
    throw new ApiError('Could not reach the server. Check your connection and try again.', 0)
  }

  if (response.status === 413) {
    const { detail } = await response.json().catch(() => ({}))
    throw new ApiError(detail ?? 'That file is too large to audit.', 413)
  }
  if (!response.ok) {
    const { detail } = await response.json().catch(() => ({}))
    throw new ApiError(detail ?? `The server returned ${response.status}.`, response.status)
  }
  return response.json()
}

// The API sleeps after fifteen minutes of nobody using it, and takes about a
// minute to come back. Nothing can make that first start faster, but it does not
// have to happen while someone waits: this is fired the moment the page loads,
// so the wake-up overlaps with reading the page and picking a file rather than
// following it. By the time a CSV is dropped the server is usually up.
//
// Deliberately unawaited and deliberately silent. It is a hint, not a step, and
// a page that cannot reach the API yet should not say so before anyone has
// asked it for anything.
let warmed = false
export function warm() {
  if (warmed || USE_FIXTURES) return
  warmed = true
  fetch(API_BASE + '/api/health', { method: 'GET', cache: 'no-store' }).catch(() => {})
}

export function profile(csv, { delimiter = null, fixture = 'profile_churn' } = {}) {
  if (USE_FIXTURES) return fromFixture(fixture)
  return post('/api/profile', { csv, delimiter })
}

export function audit(
  csv,
  { labelColumn = null, splitColumn = null, checks = null, fixture = null } = {},
) {
  if (USE_FIXTURES) {
    return fromFixture(fixture ?? (labelColumn ? 'audit_churn' : 'audit_no_label'))
  }
  return post('/api/audit', {
    csv,
    label_column: labelColumn,
    split_column: splitColumn,
    checks,
  })
}
