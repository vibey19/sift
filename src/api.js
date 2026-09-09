// The two calls the app makes, plus an offline mode that serves the captured
// responses in src/fixtures. With fixtures on, a rendering bug is unambiguously
// a rendering bug: the data came out of the real server.
//
//   VITE_USE_FIXTURES=true npm run dev
//   VITE_FIXTURE_DELAY=8000 npm run dev   (to sit in the loading state)

const USE_FIXTURES = import.meta.env.VITE_USE_FIXTURES === 'true'
const FIXTURE_DELAY = Number(import.meta.env.VITE_FIXTURE_DELAY ?? 400)

// Kept as dynamic imports so the JSON never reaches the production bundle.
const FIXTURES = {
  profile_churn: () => import('./fixtures/profile_churn.json'),
  audit_churn: () => import('./fixtures/audit_churn.json'),
  audit_reviews: () => import('./fixtures/audit_reviews.json'),
  audit_no_label: () => import('./fixtures/audit_no_label.json'),
}

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

async function post(path, body) {
  let response
  try {
    response = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
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
