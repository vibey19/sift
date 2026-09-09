import assert from 'node:assert/strict'
import { test } from 'node:test'

import { DEDUPE, DROP_COLUMN, DROP_ROWS, NORMALIZE, RELABEL, replay } from './edits.js'

const columns = ['id', 'plan', 'label']
const rows = [
  ['1', 'Premium', 'yes'],
  ['2', 'premium', 'no'],
  ['3', ' Premium ', 'yes'],
  ['1', 'Premium', 'yes'],
]

test('no edits leaves the data alone', () => {
  const out = replay(columns, rows, [])
  assert.deepEqual(out.rows, rows)
  assert.deepEqual(out.columns, columns)
})

test('dropping rows removes exactly those rows', () => {
  const out = replay(columns, rows, [{ op: DROP_ROWS, rowIndices: [1, 3] }])
  assert.deepEqual(out.sourceRows, [0, 2])
  assert.equal(out.rows.length, 2)
})

test('the original rows are never mutated', () => {
  const before = JSON.stringify(rows)
  replay(columns, rows, [
    { op: DROP_ROWS, rowIndices: [0] },
    { op: RELABEL, column: 'label', rowIndices: [1], newValue: 'yes' },
  ])
  assert.equal(JSON.stringify(rows), before)
})

test('undo is popping the last edit', () => {
  const edits = [{ op: DROP_ROWS, rowIndices: [0] }, { op: DROP_ROWS, rowIndices: [1] }]
  assert.equal(replay(columns, rows, edits).rows.length, 2)
  edits.pop()
  assert.equal(replay(columns, rows, edits).rows.length, 3)
})

test('dedupe keeps the first of each identical group', () => {
  const out = replay(columns, rows, [{ op: DEDUPE }])
  assert.deepEqual(out.sourceRows, [0, 1, 2])
})

test('dedupe sees relabelled values, not the originals', () => {
  // Rows 0 and 1 differ only in label. Relabelling row 1 makes them identical,
  // and dedupe run afterwards has to notice.
  const out = replay(['a', 'b'], [['x', '1'], ['x', '2']], [
    { op: RELABEL, column: 'b', rowIndices: [1], newValue: '1' },
    { op: DEDUPE },
  ])
  assert.equal(out.rows.length, 1)
})

test('relabel can send each row to a different value', () => {
  const out = replay(columns, rows, [
    { op: RELABEL, column: 'label', values: { 0: 'no', 2: 'no' } },
  ])
  assert.equal(out.rows[0][2], 'no')
  assert.equal(out.rows[1][2], 'no')
  assert.equal(out.rows[2][2], 'no')
})

test('normalise rewrites every spelling variant', () => {
  const out = replay(columns, rows, [
    { op: NORMALIZE, column: 'plan', from: ['premium', ' Premium '], to: 'Premium' },
  ])
  assert.deepEqual(out.rows.map((r) => r[1]), ['Premium', 'Premium', 'Premium', 'Premium'])
})

test('dropping a column removes it from the header and every row', () => {
  const out = replay(columns, rows, [{ op: DROP_COLUMN, column: 'plan' }])
  assert.deepEqual(out.columns, ['id', 'label'])
  assert.deepEqual(out.rows[0], ['1', 'yes'])
})

test('a dropped column is ignored when deduplicating', () => {
  // These two rows differ only in the column being dropped, so once it is gone
  // they are the same record and dedupe has to collapse them.
  const out = replay(['a', 'b'], [['x', '1'], ['x', '2']], [
    { op: DROP_COLUMN, column: 'b' },
    { op: DEDUPE },
  ])
  assert.equal(out.rows.length, 1)
  assert.deepEqual(out.columns, ['a'])
})

test('edits compose in the order they were made', () => {
  // Normalising makes rows 0 and 1 identical, so the dedupe that follows sees a
  // duplicate that did not exist when the log started.
  const out = replay(['plan', 'label'], [['Premium', 'y'], ['premium', 'y'], ['Basic', 'z']], [
    { op: NORMALIZE, column: 'plan', from: ['Premium', 'premium'], to: 'Premium' },
    { op: DEDUPE },
  ])
  assert.deepEqual(out.sourceRows, [0, 2])
})

test('an unknown op is ignored rather than throwing', () => {
  assert.equal(replay(columns, rows, [{ op: 'nonsense' }]).rows.length, 4)
})

test('an edit naming a missing column is ignored', () => {
  assert.equal(replay(columns, rows, [{ op: RELABEL, column: 'nope', rowIndices: [0], newValue: 'x' }]).rows.length, 4)
})
