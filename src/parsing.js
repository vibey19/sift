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
