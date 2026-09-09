// The browser half of api/sift/parsing.py. The rules are written out there;
// this implements the same ones. tests/test_parsing.py runs both over the same
// awkward headers and fails if they disagree, because a disagreement means the
// server names a column something the browser cannot find, and every fix
// touching it is silently discarded.

const CANDIDATES = [',', '\t', ';', '|']
const SAMPLE_LINES = 20
// A preamble longer than this is not a preamble, it is the file.
const MAX_PREAMBLE = 12
// A header can contain a blank name, but not mostly blank names.
const MIN_FILLED_HEADER = 0.5

const NUMERIC_CELL = /^-?[\d,]*\d(\.\d+)?$/

// Windows-1252 differs from Latin-1 only over 0x80 to 0x9F, where it puts the
// smart quotes and dashes. Written out so a character can be turned back into
// the byte it came from. The five gaps are the codes the table leaves undefined.
const CP1252_HIGH =
  '\u20ac\u0081\u201a\u0192\u201e\u2026\u2020\u2021\u02c6\u2030\u0160\u2039\u0152\u008d\u017d\u008f' +
  '\u0090\u2018\u2019\u201c\u201d\u2022\u2013\u2014\u02dc\u2122\u0161\u203a\u0153\u009d\u017e\u0178'

// Anything that could have come from a single byte. A file with none of it
// needs no further thought.
const FROM_A_BYTE = new RegExp(`[\\u0080-\\u00ff${CP1252_HIGH}]`)

function splitLines(text) {
  const lines = []
  let current = ''
  let inQuotes = false
  for (let i = 0; i < text.length; i += 1) {
    const char = text[i]
    if (char === '"') {
      if (inQuotes && text[i + 1] === '"') {
        current += '""'
        i += 1
        continue
      }
      inQuotes = !inQuotes
      current += char
    } else if ((char === '\n' || char === '\r') && !inQuotes) {
      if (char === '\r' && text[i + 1] === '\n') i += 1
      lines.push(current)
      current = ''
    } else {
      current += char
    }
  }
  if (current) lines.push(current)
  return lines
}

function countOutsideQuotes(line, delimiter) {
  let total = 0
  let inQuotes = false
  for (const char of line) {
    if (char === '"') inQuotes = !inQuotes
    else if (char === delimiter && !inQuotes) total += 1
  }
  return total
}

// Characters back to the bytes they were decoded from. `table` is the
// Windows-1252 replacements for 0x80 to 0x9F, or null for plain Latin-1.
function toBytes(text, table) {
  const bytes = new Uint8Array(text.length)
  for (let i = 0; i < text.length; i += 1) {
    const code = text.charCodeAt(i)
    if (code < 0x80 || (code <= 0xff && (table === null || code >= 0xa0))) {
      bytes[i] = code
    } else if (table !== null) {
      const at = table.indexOf(text[i])
      if (at < 0) return null
      bytes[i] = 0x80 + at
    } else {
      return null
    }
  }
  return bytes
}

function countNonAscii(text) {
  let total = 0
  for (let i = 0; i < text.length; i += 1) if (text.charCodeAt(i) > 127) total += 1
  return total
}

// Undo a file that was written as UTF-8 and read as Western European. See
// api/sift/parsing.py for why this is safe to do without asking: undamaged text
// does not survive the trip, because a real accented character is a single byte
// that is not valid UTF-8 on its own.
export function repairMojibake(text) {
  if (!FROM_A_BYTE.test(text)) return text
  const decoder = new TextDecoder('utf-8', { fatal: true })
  // Both tables are tried because both decoders are in use and they disagree
  // over 0x80 to 0x9F, which is where Cyrillic and Greek bytes land.
  for (const table of [CP1252_HIGH, null]) {
    const bytes = toBytes(text, table)
    if (!bytes) continue
    let candidate
    try {
      candidate = decoder.decode(bytes)
    } catch {
      continue
    }
    if (countNonAscii(candidate) < countNonAscii(text)) return candidate
  }
  return text
}

export function detectDelimiter(text) {
  const lines = splitLines(text)
    .filter((line) => line.trim())
    .slice(0, SAMPLE_LINES)
  if (!lines.length) return ','

  let best = ','
  let bestFields = 0
  let bestAgreement = 0
  for (const candidate of CANDIDATES) {
    const counts = lines.map((line) => countOutsideQuotes(line, candidate))
    const tally = new Map()
    for (const c of counts) tally.set(c, (tally.get(c) ?? 0) + 1)
    let modal = 0
    let modalCount = 0
    for (const [value, times] of tally) {
      if (times > modalCount) {
        modal = value
        modalCount = times
      }
    }
    if (modal === 0) continue
    const agreement = modalCount / counts.length
    if (agreement < 0.6) continue
    // More fields wins, and among equals the one that divides more of the
    // lines. A semicolon file whose values contain decimal commas has one
    // comma on most rows and one semicolon on all of them.
    if (modal > bestFields || (modal === bestFields && agreement > bestAgreement)) {
      best = candidate
      bestFields = modal
      bestAgreement = agreement
    }
  }
  return best
}

export function normaliseHeaders(raw) {
  const names = []
  const seen = new Map()
  raw.forEach((value, position) => {
    let name = String(value ?? '').trim()
    if (!name) name = `column_${position + 1}`
    if (seen.has(name)) {
      seen.set(name, seen.get(name) + 1)
      let candidate = `${name}_${seen.get(name)}`
      while (seen.has(candidate)) {
        seen.set(name, seen.get(name) + 1)
        candidate = `${name}_${seen.get(name)}`
      }
      name = candidate
    }
    if (!seen.has(name)) seen.set(name, 1)
    names.push(name)
  })
  return names
}

// How many fields the table has, ignoring anything sitting above it. Taking the
// most common count across the whole file breaks both ways: a file with two
// comment lines and two data lines has no majority, and one over-long row would
// let that row widen the table. So each of the first few lines is tried as the
// header, and the first whose count matches what most of the lines below it do
// is the table. Failing that, the first line is the header.
export function fieldWidth(text, delimiter) {
  const counts = splitLines(text)
    .filter((line) => line.trim())
    .map((line) => countOutsideQuotes(line, delimiter) + 1)
  if (!counts.length) return 1

  const limit = Math.min(counts.length - 1, MAX_PREAMBLE)
  for (let index = 0; index < limit; index += 1) {
    const below = counts.slice(index + 1, index + 1 + SAMPLE_LINES)
    if (!below.length) break
    const tally = new Map()
    for (const c of below) tally.set(c, (tally.get(c) ?? 0) + 1)
    let modal = 0
    let modalTimes = 0
    for (const [value, times] of tally) {
      if (times > modalTimes || (times === modalTimes && value > modal)) {
        modal = value
        modalTimes = times
      }
    }
    if (counts[index] === modal) return modal
  }
  return counts[0]
}

// Index of the first row shaped like a header. A spreadsheet export often opens
// with a title, a generated-on line and a blank; a hand-maintained file often
// opens with comments. All of them are narrower or emptier than the table
// underneath, which tells them apart without a rule for each.
export function findHeader(rows, width) {
  const limit = Math.min(rows.length, MAX_PREAMBLE)
  for (let index = 0; index < limit; index += 1) {
    const row = rows[index]
    const filled = row.filter((cell) => String(cell ?? '').trim()).length
    if (row.length >= width && filled / Math.max(width, 1) > MIN_FILLED_HEADER) return index
  }
  return 0
}

function looksNumeric(cell) {
  const text = String(cell ?? '').trim()
  return text !== '' && NUMERIC_CELL.test(text)
}

// How many rows the header occupies: 1 normally, 2 when it is split. A merged
// cell in a spreadsheet has no representation in CSV, so "Q1" spanning two
// columns comes out as "Q1" then a blank, with the sub-headings on the row
// below. See api/sift/parsing.py for each condition and why it is there.
export function headerSpan(rows, width, headerAt) {
  if (headerAt + 2 >= rows.length) return 1
  const top = rows[headerAt].slice(0, width)
  const bottom = rows[headerAt + 1].slice(0, width)
  if (top.length < width || bottom.length < width) return 1
  if (bottom.some(looksNumeric)) return 1
  // The first row names every column, so it is the whole header.
  if (top.every((cell) => String(cell ?? '').trim())) return 1

  const combined = combineHeaders(top, bottom, width)
  if (!combined.every(Boolean) || new Set(combined).size < width) return 1
  // One row is not enough to ask that of: the first record in a file is as
  // likely as any other to have a gap in it.
  const body = rows.slice(headerAt + 2, headerAt + 2 + SAMPLE_LINES)
  if (!body.some((row) => row.slice(0, width).some(looksNumeric))) return 1
  return 2
}

// The top row is carried across the blanks a merged cell leaves behind.
export function combineHeaders(top, bottom, width) {
  const names = []
  let parent = ''
  for (let index = 0; index < width; index += 1) {
    const above = String(top[index] ?? '').trim()
    const below = String(bottom[index] ?? '').trim()
    if (above) parent = above
    names.push(parent && below && parent !== below ? `${parent} ${below}` : below || parent)
  }
  return names
}
