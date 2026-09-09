// CSV parsing, written out rather than pulled in, because the whole point of the
// architecture is that the browser holds the file and the server never stores it.
// Follows RFC 4180: fields may be quoted, quotes escape by doubling, and a quoted
// field may contain the delimiter or a newline.

import {
  combineHeaders,
  detectDelimiter,
  fieldWidth,
  findHeader,
  headerSpan,
  normaliseHeaders,
  repairMojibake,
} from './parsing.js'

const QUOTE = '"'

export { detectDelimiter }

export function parseCsv(text, { delimiter } = {}) {
  if (typeof text !== 'string') throw new TypeError('parseCsv expects a string')
  // A byte order mark would otherwise become part of the first column name and
  // every later lookup by that name would miss.
  // Repaired before a character of it is read. A file written as UTF-8 and
  // read as Western European carries the damage in its column names too, and
  // a column named with the damage in it is one no fix can find afterwards.
  const source = repairMojibake(text.charCodeAt(0) === 0xfeff ? text.slice(1) : text)
  const sep = delimiter ?? detectDelimiter(source)

  const rows = []
  let row = []
  let field = ''
  let inQuotes = false
  let started = false

  const endField = () => {
    row.push(field)
    field = ''
    started = false
  }
  const endRow = () => {
    endField()
    // A trailing newline produces one empty field, which is not a row.
    if (!(row.length === 1 && row[0] === '')) rows.push(row)
    row = []
  }

  for (let i = 0; i < source.length; i += 1) {
    const char = source[i]

    if (inQuotes) {
      if (char === QUOTE) {
        if (source[i + 1] === QUOTE) {
          field += QUOTE
          i += 1
        } else {
          inQuotes = false
        }
      } else {
        field += char
      }
      continue
    }

    if (char === QUOTE && !started) {
      inQuotes = true
      started = true
    } else if (char === sep) {
      endField()
    } else if (char === '\n') {
      endRow()
    } else if (char === '\r') {
      // Swallow CRLF; a lone CR is treated as a line ending too.
      if (source[i + 1] === '\n') i += 1
      endRow()
    } else {
      field += char
      started = true
    }
  }
  if (field !== '' || row.length) endRow()

  if (!rows.length) return { columns: [], rows: [], delimiter: sep }

  // Line one is often a title, a generated-on stamp or a comment. The header is
  // the first row shaped like one, and anything above it is dropped.
  const width = fieldWidth(source, sep)
  const headerAt = findHeader(rows, width)
  const pad = (cells) =>
    cells.length >= width ? cells.slice(0, width) : cells.concat(Array(width - cells.length).fill(''))
  // A header split over two rows is what a merged spreadsheet cell becomes.
  const span = headerSpan(rows, width, headerAt)
  const columns = normaliseHeaders(
    span === 1
      ? pad(rows[headerAt])
      : combineHeaders(pad(rows[headerAt]), pad(rows[headerAt + 1]), width),
  )
  const body = rows.slice(headerAt + span).map((cells) => {
    if (cells.length === width) return cells
    // Ragged rows are common in exports and are not worth rejecting a file over.
    // C1 will report the gaps that padding creates.
    return cells.length < width
      ? cells.concat(Array(width - cells.length).fill(''))
      : cells.slice(0, width)
  })

  return { columns, rows: body, delimiter: sep }
}

const NEEDS_QUOTING = /[",\n\r\t;]/

export function toCsv(columns, rows, delimiter = ',') {
  const cell = (value) => {
    const text = value == null ? '' : String(value)
    return NEEDS_QUOTING.test(text) ? QUOTE + text.split(QUOTE).join(QUOTE + QUOTE) + QUOTE : text
  }
  const lines = [columns.map(cell).join(delimiter)]
  for (const row of rows) lines.push(row.map(cell).join(delimiter))
  return lines.join('\n') + '\n'
}

export function columnIndex(columns) {
  return Object.fromEntries(columns.map((name, i) => [name, i]))
}
