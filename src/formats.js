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

export function parseNumber(value) {
  let text = String(value ?? '').trim()
  if (!text) return null

  // Accountants write a negative as (1,234.00).
  const negative = text.startsWith('(') && text.endsWith(')')
  if (negative) text = text.slice(1, -1).trim()

  text = text.replace(CURRENCY, '').trim()
  text = text.replace(/(?<=\d),(?=\d{3}\b)/g, '')
  if (/^-?[\d\s]*\.?\d+$/.test(text)) text = text.replace(/\s/g, '')
  if (text.startsWith('- ')) text = `-${text.slice(1).trim()}`

  const match = NUMBER.exec(text.trim())
  if (!match) return null
  const number = Number(match[1])
  if (!Number.isFinite(number)) return null
  return negative ? -number : number
}

// Trailing zeros from a float are noise in a CSV. 4.20 becomes 4.2, 5.0 becomes 5.
export function formatNumber(n) {
  return String(Math.round(n * 1e9) / 1e9)
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
