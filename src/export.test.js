// The phase 6 gate: drop flagged rows, export, and confirm exactly those rows
// are gone and nothing else moved.

import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

import { parseCsv, toCsv } from './csv.js'
import { DEDUPE, DROP_COLUMN, DROP_ROWS, replay } from './edits.js'

const source = readFileSync(new URL('../public/samples/churn_dirty.csv', import.meta.url), 'utf8')
const original = parseCsv(source)
const audit = JSON.parse(
  readFileSync(new URL('./fixtures/audit_churn.json', import.meta.url), 'utf8'),
)

const issue = (check) => audit.issues.find((i) => i.check === check)
const key = (row) => row.join('')

function exportAndReparse(edits) {
  const current = replay(original.columns, original.rows, edits)
  return { current, exported: parseCsv(toCsv(current.columns, current.rows)) }
}

test('the sample parses to the size the API reported', () => {
  assert.equal(original.rows.length, 3075)
  assert.equal(original.columns.length, 14)
})

test('dropping the contaminated rows removes exactly those rows', () => {
  const contaminated = issue('D4_train_test_overlap').row_indices
  const { exported } = exportAndReparse([{ op: DROP_ROWS, rowIndices: contaminated }])

  assert.equal(exported.rows.length, original.rows.length - contaminated.length)

  // Every surviving row is byte-identical to the row it came from, in order.
  const dropped = new Set(contaminated)
  const expected = original.rows.filter((_, i) => !dropped.has(i))
  assert.deepEqual(exported.rows, expected)

  // A dropped row may only reappear if an unflagged identical copy explains it.
  const survivors = new Set(exported.rows.map(key))
  for (const i of contaminated) {
    if (!survivors.has(key(original.rows[i]))) continue
    const copies = original.rows.filter((r) => key(r) === key(original.rows[i]))
    assert.ok(copies.length > 1, `row ${i} survived without a duplicate to explain it`)
  }
})

test('the header survives the round trip unchanged', () => {
  const { exported } = exportAndReparse([{ op: DROP_ROWS, rowIndices: [0, 1, 2] }])
  assert.deepEqual(exported.columns, original.columns)
})

test('dropping the leaked column removes it and keeps every row', () => {
  const leaked = issue('C10_leakage').column
  const { exported } = exportAndReparse([{ op: DROP_COLUMN, column: leaked }])
  assert.equal(exported.rows.length, original.rows.length)
  assert.ok(!exported.columns.includes(leaked))
  assert.equal(exported.columns.length, original.columns.length - 1)
})

test('dedupe leaves one copy of each duplicated record', () => {
  const { exported } = exportAndReparse([{ op: DEDUPE }])
  const keys = exported.rows.map(key)
  assert.equal(new Set(keys).size, keys.length, 'export still contains duplicates')
  assert.equal(exported.rows.length, new Set(original.rows.map(key)).size)
})

test('values containing commas, quotes and newlines survive export', () => {
  const columns = ['note', 'n']
  const rows = [['Smith, John said "hi"', '1'], ['line\nbreak', '2'], ['tab\there', '3']]
  const current = replay(columns, rows, [])
  assert.deepEqual(parseCsv(toCsv(current.columns, current.rows)).rows, rows)
})

test('an empty edit log exports the file it was given', () => {
  const { exported } = exportAndReparse([])
  assert.deepEqual(exported.rows, original.rows)
  assert.deepEqual(exported.columns, original.columns)
})
