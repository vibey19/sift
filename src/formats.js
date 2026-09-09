// The browser half of api/sift/formats.py. The server decides a column can be
// read as numbers or dates; this rewrites the values. The two must agree, and
// tests/test_formats.py checks that they do against a shared list of awkward
// values, because a disagreement means the preview and the export disagree.

const CURRENCY = /[$€£¥₹₽¢]/g
const NUMBER = /^(-?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*[a-zA-Z°%/²³]{0,4}$/

const MONTHS = {
  jan: 1, feb: 2, mar: 3, apr: 4, may: 5, jun: 6,
  jul: 7, aug: 8, sep: 9, oct: 10, nov: 11, dec: 12,
}

const TRUE_WORDS = new Set(['true', 't', 'yes', 'y', '1', 'on'])
const FALSE_WORDS = new Set(['false', 'f', 'no', 'n', '0', 'off'])

// The number inside a formatted value, and the decoration around it. The number
// comes back as the text it was written as and never as a Number, because a
// Number cannot hold 9007199254740993 and cannot hold 007 either. See
// api/sift/formats.py for the longer version of why that matters.
export function numberParts(value) {
  let text = String(value ?? '').trim()
  if (!text) return null

  // Accountants write a negative as (1,234.00).
  const negative = text.startsWith('(') && text.endsWith(')')
  if (negative) text = text.slice(1, -1).trim()

  const symbols = text.match(CURRENCY) ?? []
  text = text.replace(CURRENCY, '').trim()
  const grouped = /^-?\d{1,3}(,\d{3})+(\.\d+)?\s*/.test(text)
  if (grouped) text = text.replace(/(?<=\d),(?=\d{3})/g, '')
  if (/^-?[\d\s]*\.?\d+$/.test(text)) text = text.replace(/\s/g, '')
  if (text.startsWith('- ')) text = `-${text.slice(1).trim()}`

  text = text.trim()
  const match = NUMBER.exec(text)
  if (!match) return null
  let literal = match[1]
  const unit = text.slice(literal.length).trim()
  if (negative) literal = literal.startsWith('-') ? literal.slice(1) : `-${literal}`
  return { literal, symbol: symbols[0] ?? '', unit, negative, grouped }
}

// The number as text, decoration removed and nothing else changed. Every digit
// that was written is still there afterwards.
export function stripNumberFormatting(value) {
  const parts = numberParts(value)
  return parts === null ? null : parts.literal
}

// Lossy by nature, and used only where a Number is what is wanted. Anything
// that writes a value back into the file uses stripNumberFormatting.
export function parseNumber(value) {
  const literal = stripNumberFormatting(value)
  if (literal === null) return null
  const number = Number(literal)
  return Number.isFinite(number) ? number : null
}


function iso(year, month, day) {
  if (!(month >= 1 && month <= 12 && day >= 1 && day <= 31)) return null
  return `${String(year).padStart(4, '0')}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

export function parseDate(value, dayfirst = false) {
  const text = String(value ?? '').trim()
  if (!text) return null

  let m = /^(\d{4})[-/](\d{1,2})[-/](\d{1,2})/.exec(text)
  if (m) return iso(+m[1], +m[2], +m[3])

  m = /^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$/.exec(text)
  if (m) {
    const a = +m[1]
    const b = +m[2]
    const y = +m[3]
    // A value above 12 can only be the day, whichever order was intended.
    if (a > 12) return iso(y, b, a)
    if (b > 12) return iso(y, a, b)
    return dayfirst ? iso(y, b, a) : iso(y, a, b)
  }

  m = /^(\d{1,2})[-\s]([A-Za-z]{3,9})[-\s,]+(\d{4})$/.exec(text)
  if (m) {
    const month = MONTHS[m[2].slice(0, 3).toLowerCase()]
    return month ? iso(+m[3], month, +m[1]) : null
  }

  m = /^([A-Za-z]{3,9})[-\s]+(\d{1,2})[-\s,]+(\d{4})$/.exec(text)
  if (m) {
    const month = MONTHS[m[1].slice(0, 3).toLowerCase()]
    return month ? iso(+m[3], month, +m[2]) : null
  }

  return null
}

export function parseBoolean(value) {
  const text = String(value ?? '').trim().toLowerCase()
  if (TRUE_WORDS.has(text)) return true
  if (FALSE_WORDS.has(text)) return false
  return null
}


// --- markup and invisible characters ----------------------------------------
// The twin of api/sift/formats.py. Written by code point on both sides so no
// character here depends on surviving a copy and paste, and tests/test_formats.py
// fails if the two ever disagree about a value.
const ENTITIES = {
  amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ',
  ndash: '\u2013', mdash: '\u2014', hellip: '\u2026',
  lsquo: '\u2018', rsquo: '\u2019', ldquo: '\u201c', rdquo: '\u201d',
  bull: '\u2022', middot: '\u00b7', deg: '\u00b0', copy: '\u00a9',
  reg: '\u00ae', trade: '\u2122', euro: '\u20ac', pound: '\u00a3',
}

const TAG = /<\/?[a-zA-Z][a-zA-Z0-9]*(?:\s[^<>]*)?\/?>/g
const ENTITY = new RegExp(
  `&(?:${Object.keys(ENTITIES).sort().join('|')}|#\\d{1,5}|#x[0-9a-fA-F]{1,4});`,
  'g',
)

export const MARKUP = new RegExp(`${TAG.source}|${ENTITY.source}`)

function entity(match) {
  const body = match.slice(1, -1)
  if (body.startsWith('#')) {
    const code = body[1] === 'x' || body[1] === 'X' ? parseInt(body.slice(2), 16) : Number(body.slice(1))
    return Number.isFinite(code) && code > 0 && code <= 0x10ffff ? String.fromCodePoint(code) : match
  }
  return ENTITIES[body] ?? match
}

// Tags become a space rather than nothing, so "one<br>two" does not come back
// as one word, and the run of spaces that leaves is collapsed afterwards.
export function stripMarkup(value) {
  return String(value ?? '')
    .replace(TAG, ' ')
    .replace(ENTITY, entity)
    .split(/\s+/)
    .filter(Boolean)
    .join(' ')
}

const ZERO_WIDTH = '\u200b\u200c\u200d\u2060\ufeff\u200e\u200f\u00ad'
const SPACE_LIKE = '\u00a0\u2007\u202f\u2009\u2002\u2003'
export const INVISIBLE = new RegExp(`[${ZERO_WIDTH}${SPACE_LIKE}]`)

export function stripInvisible(value) {
  let out = ''
  for (const char of String(value ?? '')) {
    if (ZERO_WIDTH.includes(char)) continue
    out += SPACE_LIKE.includes(char) ? ' ' : char
  }
  return out
}
