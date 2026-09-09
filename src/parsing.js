// The browser half of api/sift/parsing.py. The rules are written out there;
// this implements the same ones. tests/test_parsing.py runs both over the same
// awkward headers and fails if they disagree, because a disagreement means the
// server names a column something the browser cannot find, and every fix
// touching it is silently discarded.

const CANDIDATES = [',', '\t', ';', '|']
const SAMPLE_LINES = 20

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
