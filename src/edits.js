// Edits are an append-only log, not a mutation of the table. Every render and
// every export replays the log over the original rows, which makes undo a pop
// and keeps the parsed file authoritative: nothing is ever lost, only shadowed.
//
// The cost is replaying on each render. That is why App memoises this on the
// log's length, and why replay is one linear pass over the rows.

import { columnIndex } from './csv.js'

export const DROP_ROWS = 'drop_rows'
export const DEDUPE = 'dedupe'
export const RELABEL = 'relabel'
export const NORMALIZE = 'normalize_values'
export const DROP_COLUMN = 'drop_column'

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
    default:
      return edit.op
  }
}
