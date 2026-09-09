// Edits are an append-only log, not a mutation of the table. Every render and
// every export replays the log over the original rows, which makes undo a pop
// and keeps the parsed file authoritative: nothing is ever lost, only shadowed.
//
// The cost is replaying on each render. That is why App memoises this on the
// log's length, and why replay is one linear pass over the rows.

import { columnIndex } from './csv.js'
import { formatNumber, parseBoolean, parseDate, parseNumber } from './formats.js'

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

function normalise(value) {
  return String(value ?? '').trim().toLowerCase().replace(/\s+/g, ' ')
}

export function replay(columns, rows, edits) {
  const index = columnIndex(columns)
  const droppedRows = new Set()
  const droppedColumns = new Set()
  const overrides = new Map() // `${row}:${col}` -> value

  const cellAt = (row, col) => overrides.get(`${row}:${col}`) ?? rows[row][col]

  for (const edit of edits) {
    switch (edit.op) {
      case DROP_ROWS:
        for (const row of edit.rowIndices) droppedRows.add(row)
        break

      case DROP_COLUMN:
        droppedColumns.add(edit.column)
        break

      case RELABEL: {
        const col = index[edit.column]
        if (col == null) break
        // Each row may go to a different label, which is how R1 hands back its
        // per-row prediction. A single newValue applies to all of them.
        for (const [row, value] of Object.entries(edit.values ?? {})) {
          overrides.set(`${row}:${col}`, value)
        }
        if (edit.newValue != null) {
          for (const row of edit.rowIndices ?? []) overrides.set(`${row}:${col}`, edit.newValue)
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
            overrides.set(`${row}:${col}`, edit.to)
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
          if (forms.has(normalise(cellAt(row, col)))) overrides.set(`${row}:${col}`, '')
        }
        break
      }

      case FILL_MISSING: {
        const col = index[edit.column]
        if (col == null) break
        for (let row = 0; row < rows.length; row += 1) {
          if (droppedRows.has(row)) continue
          if (String(cellAt(row, col) ?? '').trim() === '') {
            overrides.set(`${row}:${col}`, edit.value)
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
          if (value !== undefined) overrides.set(`${row}:${col}`, value)
        }
        break
      }

      case FILL_FROM_FORMULA: {
        const col = index[edit.column]
        const a = index[edit.left]
        const b = index[edit.right]
        if (col == null || a == null || b == null) break
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
          // precision no money or count needs to exceed.
          overrides.set(`${row}:${col}`, String(Math.round(value * 1e6) / 1e6))
        }
        break
      }

      case REFORMAT_NUMBER: {
        const col = index[edit.column]
        if (col == null) break
        for (let row = 0; row < rows.length; row += 1) {
          if (droppedRows.has(row)) continue
          const raw = cellAt(row, col)
          const number = parseNumber(raw)
          // Anything that is not a number is left exactly as it was, rather
          // than being blanked for failing to be one.
          if (number !== null) overrides.set(`${row}:${col}`, formatNumber(number))
        }
        break
      }

      case REFORMAT_DATE: {
        const col = index[edit.column]
        if (col == null) break
        for (let row = 0; row < rows.length; row += 1) {
          if (droppedRows.has(row)) continue
          const value = parseDate(cellAt(row, col), edit.dayfirst)
          if (value !== null) overrides.set(`${row}:${col}`, value)
        }
        break
      }

      case NORMALIZE_BOOLEAN: {
        const col = index[edit.column]
        if (col == null) break
        for (let row = 0; row < rows.length; row += 1) {
          if (droppedRows.has(row)) continue
          const value = parseBoolean(cellAt(row, col))
          if (value !== null) overrides.set(`${row}:${col}`, value ? 'true' : 'false')
        }
        break
      }

      case TRIM: {
        for (let row = 0; row < rows.length; row += 1) {
          if (droppedRows.has(row)) continue
          for (let col = 0; col < columns.length; col += 1) {
            const value = String(cellAt(row, col) ?? '')
            const trimmed = value.trim()
            if (trimmed !== value) overrides.set(`${row}:${col}`, trimmed)
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
          if (seen.has(key)) droppedRows.add(row)
          else seen.add(key)
        }
        break
      }

      default:
        break
    }
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

  return { columns: keptColumns, rows: keptRows, sourceRows, droppedRows, droppedColumns, cellAt }
}

export function describe(edit) {
  const n = edit.rowIndices?.length ?? Object.keys(edit.values ?? {}).length
  switch (edit.op) {
    case DROP_ROWS:
      return `dropped ${n} rows`
    case DEDUPE:
      return 'removed duplicate rows'
    case RELABEL:
      return `relabelled ${n} rows in '${edit.column}'`
    case NORMALIZE:
      return `normalised ${edit.from.length} spellings in '${edit.column}'`
    case DROP_COLUMN:
      return `dropped column '${edit.column}'`
    case BLANK_VALUES:
      return `blanked ${edit.forms.map((f) => `'${f}'`).join(' and ')} in '${edit.column}'`
    case FILL_MISSING:
      return `filled the gaps in '${edit.column}' with '${edit.value}'`
    case FILL_FROM_COLUMN:
      return `filled '${edit.column}' from '${edit.source}'`
    case FILL_FROM_FORMULA:
      return `computed the missing '${edit.column}' from '${edit.left}' and '${edit.right}'`
    case TRIM:
      return 'trimmed surrounding whitespace'
    case REFORMAT_NUMBER:
      return `read '${edit.column}' as numbers`
    case REFORMAT_DATE:
      return `rewrote the dates in '${edit.column}' as YYYY-MM-DD`
    case NORMALIZE_BOOLEAN:
      return `wrote '${edit.column}' consistently as true and false`
    default:
      return edit.op
  }
}
