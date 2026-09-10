// Edits are an append-only log, not a mutation of the table. Every render and
// every export replays the log over the original rows, which makes undo a pop
// and keeps the parsed file authoritative: nothing is ever lost, only shadowed.
//
// The cost is replaying on each render. That is why App memoises this on the
// log's length, and why replay is one linear pass over the rows.

import { columnIndex } from './csv.js'
import {
  parseBoolean,
  parseDate,
  stripInvisible,
  stripMarkup,
  stripNumberFormatting,
} from './formats.js'

export const DROP_ROWS = 'drop_rows'
export const DEDUPE = 'dedupe'
export const RELABEL = 'relabel'
export const NORMALIZE = 'normalize_values'
export const DROP_COLUMN = 'drop_column'
export const BLANK_VALUES = 'blank_values'
export const FILL_MISSING = 'fill_missing'
export const FILL_FROM_COLUMN = 'fill_from_column'
export const FILL_FROM_FORMULA = 'fill_from_formula'
export const TRIM = 'trim'
export const REFORMAT_NUMBER = 'reformat_number'
export const REFORMAT_DATE = 'reformat_date'
export const NORMALIZE_BOOLEAN = 'normalize_boolean'
export const STRIP_MARKUP = 'strip_markup'
export const STRIP_INVISIBLE = 'strip_invisible'

function normalise(value) {
  return String(value ?? '').trim().toLowerCase().replace(/\s+/g, ' ')
}

// The number of decimal places this column already uses, or null if it does not
// agree with itself. Taken from the values as they stand rather than from the
// original rows, so an earlier fix that reformatted the column is respected.
function columnDecimals(rows, col, cellAt, droppedRows) {
  const seen = new Map()
  for (let row = 0; row < rows.length; row += 1) {
    if (droppedRows.has(row)) continue
    const text = String(cellAt(row, col) ?? '').trim()
    if (!/^-?\d+(\.\d+)?$/.test(text)) continue
    const dot = text.indexOf('.')
    const places = dot < 0 ? 0 : text.length - dot - 1
    seen.set(places, (seen.get(places) ?? 0) + 1)
  }
  if (!seen.size) return null
  let best = null
  let bestCount = 0
  let total = 0
  for (const [places, count] of seen) {
    total += count
    if (count > bestCount) {
      best = places
      bestCount = count
    }
  }
  // Only when the column is close to unanimous. A column of genuinely varied
  // precision should not have a computed value rounded to fit the majority.
  return bestCount / total > 0.9 ? best : null
}

export function replay(columns, rows, edits) {
  const index = columnIndex(columns)
  const droppedRows = new Set()
  const droppedColumns = new Set()
  const overrides = new Map() // `${row}:${col}` -> value

  const cellAt = (row, col) => overrides.get(`${row}:${col}`) ?? rows[row][col]

  // What each edit changed, in the order they were applied. The count an issue
  // carries is what the check saw in the file as it arrived, and by the time a
  // fix runs the ones before it have moved the ground under it: C11 blanks
  // twenty sentinels and the fill that follows then touches sixty cells rather
  // than the forty C1 counted. Reporting the estimate as though it were the
  // result is how an edit log ends up disagreeing with the file beside it.
  const applied = []
  let changed = 0
  const setCell = (row, col, value) => {
    if (String(cellAt(row, col) ?? '') === String(value)) return
    overrides.set(`${row}:${col}`, value)
    changed += 1
  }
  const dropRow = (row) => {
    if (droppedRows.has(row)) return
    droppedRows.add(row)
    changed += 1
  }

  for (const edit of edits) {
    changed = 0
    switch (edit.op) {
      case DROP_ROWS:
        for (const row of edit.rowIndices) dropRow(row)
        break

      case DROP_COLUMN:
        if (!droppedColumns.has(edit.column) && index[edit.column] != null) changed = 1
        droppedColumns.add(edit.column)
        break

      case RELABEL: {
        const col = index[edit.column]
        if (col == null) break
        // Each row may go to a different label, which is how R1 hands back its
        // per-row prediction. A single newValue applies to all of them.
        for (const [row, value] of Object.entries(edit.values ?? {})) {
          setCell(row, col, value)
        }
        if (edit.newValue != null) {
          for (const row of edit.rowIndices ?? []) setCell(row, col, edit.newValue)
        }
        break
      }

      case NORMALIZE: {
        const col = index[edit.column]
        if (col == null) break
        const targets = new Set((edit.from ?? []).map(normalise))
        for (let row = 0; row < rows.length; row += 1) {
          if (droppedRows.has(row)) continue
          if (targets.has(normalise(cellAt(row, col)))) {
            setCell(row, col, edit.to)
          }
        }
        break
      }

      case BLANK_VALUES: {
        const col = index[edit.column]
        if (col == null) break
        const forms = new Set((edit.forms ?? []).map(normalise))
        for (let row = 0; row < rows.length; row += 1) {
          if (droppedRows.has(row)) continue
          if (forms.has(normalise(cellAt(row, col)))) setCell(row, col, '')
        }
        break
      }

      case FILL_MISSING: {
        const col = index[edit.column]
        if (col == null) break
        for (let row = 0; row < rows.length; row += 1) {
          if (droppedRows.has(row)) continue
          if (String(cellAt(row, col) ?? '').trim() === '') {
            setCell(row, col, edit.value)
          }
        }
        break
      }

      case FILL_FROM_COLUMN: {
        // Deduction, not imputation: the value is looked up from a column the
        // server proved determines this one.
        const col = index[edit.column]
        const from = index[edit.source]
        if (col == null || from == null) break
        for (let row = 0; row < rows.length; row += 1) {
          if (droppedRows.has(row)) continue
          if (String(cellAt(row, col) ?? '').trim() !== '') continue
          const key = String(cellAt(row, from) ?? '')
          const value = edit.mapping?.[key]
          if (value !== undefined) setCell(row, col, value)
        }
        break
      }

      case FILL_FROM_FORMULA: {
        const col = index[edit.column]
        const a = index[edit.left]
        const b = index[edit.right]
        if (col == null || a == null || b == null) break
        // How this column writes a number, so a computed one looks like the
        // ones already there. Writing 2 into a column of 2.0 is not just untidy:
        // the lookup that fills the item from the price is keyed on the text,
        // so "2" misses a table that says "2.0" and the row ends up labelled
        // Unknown when the file could name it.
        const decimals = columnDecimals(rows, col, cellAt, droppedRows)
        for (let row = 0; row < rows.length; row += 1) {
          if (droppedRows.has(row)) continue
          if (String(cellAt(row, col) ?? '').trim() !== '') continue
          const x = Number(cellAt(row, a))
          const y = Number(cellAt(row, b))
          if (!Number.isFinite(x) || !Number.isFinite(y)) continue
          if (edit.operation === 'quotient' && y === 0) continue
          const value =
            edit.operation === 'product'
              ? x * y
              : edit.operation === 'sum'
                ? x + y
                : edit.operation === 'quotient'
                  ? x / y
                  : x - y
          // Floating point makes 4.199999999999999 out of 1.4 * 3. Rounded to a
          // precision no money or count needs to exceed, then written to match.
          const rounded = Math.round(value * 1e6) / 1e6
          setCell(row, col, decimals === null ? String(rounded) : rounded.toFixed(decimals))
        }
        break
      }

      case REFORMAT_NUMBER: {
        const col = index[edit.column]
        if (col == null) break
        for (let row = 0; row < rows.length; row += 1) {
          if (droppedRows.has(row)) continue
          const raw = cellAt(row, col)
          // Textual, so that no digit is lost on the way through. Reading the
          // value into a Number and printing it back out turns an account
          // number of 9007199254740993 into ...992 and an 007 into 7, neither
          // of which any user would ever think to check for.
          const bare = stripNumberFormatting(raw)
          // Anything that is not a number is left exactly as it was, rather
          // than being blanked for failing to be one.
          if (bare !== null) setCell(row, col, bare)
        }
        break
      }

      case REFORMAT_DATE: {
        const col = index[edit.column]
        if (col == null) break
        for (let row = 0; row < rows.length; row += 1) {
          if (droppedRows.has(row)) continue
          const value = parseDate(cellAt(row, col), edit.dayfirst)
          if (value !== null) setCell(row, col, value)
        }
        break
      }

      case NORMALIZE_BOOLEAN: {
        const col = index[edit.column]
        if (col == null) break
        for (let row = 0; row < rows.length; row += 1) {
          if (droppedRows.has(row)) continue
          const value = parseBoolean(cellAt(row, col))
          if (value !== null) setCell(row, col, value ? 'true' : 'false')
        }
        break
      }

      case STRIP_MARKUP: {
        const col = index[edit.column]
        if (col == null) break
        for (let row = 0; row < rows.length; row += 1) {
          if (droppedRows.has(row)) continue
          const value = String(cellAt(row, col) ?? '')
          const stripped = stripMarkup(value)
          if (stripped !== value) setCell(row, col, stripped)
        }
        break
      }

      case STRIP_INVISIBLE: {
        // Every column, because a zero-width character is not a property of the
        // column it landed in. It came from wherever the text was copied from.
        for (let row = 0; row < rows.length; row += 1) {
          if (droppedRows.has(row)) continue
          for (let col = 0; col < columns.length; col += 1) {
            const value = String(cellAt(row, col) ?? '')
            const stripped = stripInvisible(value)
            if (stripped !== value) setCell(row, col, stripped)
          }
        }
        break
      }

      case TRIM: {
        for (let row = 0; row < rows.length; row += 1) {
          if (droppedRows.has(row)) continue
          for (let col = 0; col < columns.length; col += 1) {
            const value = String(cellAt(row, col) ?? '')
            const trimmed = value.trim()
            if (trimmed !== value) setCell(row, col, trimmed)
          }
        }
        break
      }

      case DEDUPE: {
        // Deduplicating after a relabel has to see the relabelled values, so the
        // key is built from the current state rather than the original row.
        const seen = new Set()
        const live = columns.map((name, i) => (droppedColumns.has(name) ? -1 : i)).filter((i) => i >= 0)
        for (let row = 0; row < rows.length; row += 1) {
          if (droppedRows.has(row)) continue
          const key = JSON.stringify(live.map((col) => cellAt(row, col)))
          if (seen.has(key)) dropRow(row)
          else seen.add(key)
        }
        break
      }

      default:
        break
    }
    applied.push({ op: edit.op, column: edit.column ?? null, changed })
  }

  const keptColumns = columns.filter((name) => !droppedColumns.has(name))
  const keptIndexes = columns.map((name, i) => [name, i]).filter(([name]) => !droppedColumns.has(name))
  const keptRows = []
  const sourceRows = []
  for (let row = 0; row < rows.length; row += 1) {
    if (droppedRows.has(row)) continue
    keptRows.push(keptIndexes.map(([, col]) => cellAt(row, col)))
    sourceRows.push(row)
  }

  return {
    columns: keptColumns,
    rows: keptRows,
    sourceRows,
    droppedRows,
    droppedColumns,
    cellAt,
    applied,
  }
}

export function describe(edit, changed) {
  // `changed` is what replay measured. Without it these fall back to what the
  // edit asked for, which is the right thing to say before it has run.
  const n = changed ?? edit.rowIndices?.length ?? Object.keys(edit.values ?? {}).length
  const cells = changed == null ? '' : ` (${changed.toLocaleString()} cells)`
  switch (edit.op) {
    case DROP_ROWS:
      return `dropped ${n.toLocaleString()} rows`
    case DEDUPE:
      return changed == null
        ? 'removed duplicate rows'
        : `removed ${changed.toLocaleString()} duplicate rows`
    case RELABEL:
      return `relabelled ${n.toLocaleString()} rows in '${edit.column}'`
    case NORMALIZE:
      return `normalised ${edit.from.length} spellings in '${edit.column}'${cells}`
    case DROP_COLUMN:
      return `dropped column '${edit.column}'`
    case BLANK_VALUES:
      return `blanked ${edit.forms.map((f) => `'${f}'`).join(' and ')} in '${edit.column}'${cells}`
    case FILL_MISSING:
      return `filled ${changed == null ? 'the gaps' : `${changed.toLocaleString()} gaps`} in '${edit.column}' with '${edit.value}'`
    case FILL_FROM_COLUMN:
      return `filled '${edit.column}' from '${edit.source}'${cells}`
    case FILL_FROM_FORMULA:
      return `computed the missing '${edit.column}' from '${edit.left}' and '${edit.right}'${cells}`
    case TRIM:
      return `trimmed surrounding whitespace${cells}`
    case REFORMAT_NUMBER:
      return `read '${edit.column}' as numbers${cells}`
    case REFORMAT_DATE:
      return `rewrote the dates in '${edit.column}' as YYYY-MM-DD${cells}`
    case NORMALIZE_BOOLEAN:
      return `wrote '${edit.column}' consistently as true and false${cells}`
    case STRIP_MARKUP:
      return `took the HTML out of '${edit.column}'${cells}`
    case STRIP_INVISIBLE:
      return `removed the zero-width characters${cells}`
    default:
      return edit.op
  }
}
