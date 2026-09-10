import assert from 'node:assert/strict'
import { test } from 'node:test'

import {
  BLANK_VALUES,
  DEDUPE,
  DROP_COLUMN,
  DROP_ROWS,
  FILL_FROM_COLUMN,
  FILL_FROM_FORMULA,
  FILL_MISSING,
  NORMALIZE,
  RELABEL,
  STRIP_INVISIBLE,
  STRIP_MARKUP,
  TRIM,
  describe,
  replay,
} from './edits.js'

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

test('blanking replaces every spelling of a sentinel with nothing', () => {
  const out = replay(['a'], [['ERROR'], ['ok'], ['unknown']], [
    { op: BLANK_VALUES, column: 'a', forms: ['ERROR', 'UNKNOWN'] },
  ])
  assert.deepEqual(out.rows.map((r) => r[0]), ['', 'ok', ''])
})

test('filling a gap does not overwrite a value that is already there', () => {
  const out = replay(['a'], [['x'], [''], ['  ']], [
    { op: FILL_MISSING, column: 'a', value: 'Unknown' },
  ])
  assert.deepEqual(out.rows.map((r) => r[0]), ['x', 'Unknown', 'Unknown'])
})

test('filling from another column is a lookup, not a guess', () => {
  const out = replay(['item', 'price'], [['Tea', ''], ['Cake', ''], ['Beer', '']], [
    { op: FILL_FROM_COLUMN, column: 'price', source: 'item', mapping: { Tea: '1.5', Cake: '3' } },
  ])
  // Beer is not in the mapping, so it stays empty rather than being invented.
  assert.deepEqual(out.rows.map((r) => r[1]), ['1.5', '3', ''])
})

test('a formula fills whichever term is missing', () => {
  const rows = [['2', '3', ''], ['', '3', '12'], ['2', '', '10']]
  const product = replay(['q', 'p', 't'], rows, [
    { op: FILL_FROM_FORMULA, column: 't', left: 'q', right: 'p', operation: 'product' },
  ])
  assert.equal(product.rows[0][2], '6')

  const quotient = replay(['q', 'p', 't'], rows, [
    { op: FILL_FROM_FORMULA, column: 'q', left: 't', right: 'p', operation: 'quotient' },
  ])
  assert.equal(quotient.rows[1][0], '4')
})

test('a formula never divides by zero', () => {
  const out = replay(['a', 'b', 'c'], [['', '0', '5']], [
    { op: FILL_FROM_FORMULA, column: 'a', left: 'c', right: 'b', operation: 'quotient' },
  ])
  assert.equal(out.rows[0][0], '', 'dividing by zero should leave the cell alone')
})

test('floating point noise does not leak into the file', () => {
  const out = replay(['q', 'p', 't'], [['3', '1.4', '']], [
    { op: FILL_FROM_FORMULA, column: 't', left: 'q', right: 'p', operation: 'product' },
  ])
  assert.equal(out.rows[0][2], '4.2', 'expected 4.2, not 4.199999999999999')
})

test('trim strips padding from every column', () => {
  const out = replay(['a', 'b'], [[' 1 ', 'x  '], ['2', ' y']], [{ op: TRIM }])
  assert.deepEqual(out.rows, [['1', 'x'], ['2', 'y']])
})

// --- the two ops that remove characters rather than rows ---------------------

test('stripping markup leaves the words and the spacing between them', () => {
  const out = replay(
    ['body'],
    [['Great <b>product</b> &amp; fast'], ['one<br>two'], ['a < b and 3 > 2']],
    [{ op: STRIP_MARKUP, column: 'body' }],
  )
  assert.deepEqual(out.rows, [['Great product & fast'], ['one two'], ['a < b and 3 > 2']])
})

test('stripping invisible characters runs over every column', () => {
  // A zero-width character is not a property of the column it landed in; it
  // came from wherever the text was copied from, so the op is not per column.
  const out = replay(
    ['city', 'note'],
    [['Lon​don', 'New York'], ['Leeds', 'fine']],
    [{ op: STRIP_INVISIBLE }],
  )
  assert.deepEqual(out.rows, [['London', 'New York'], ['Leeds', 'fine']])
})

test('a value with nothing wrong with it is left byte for byte alone', () => {
  const original = [['plain text'], ['AT&T and R&D']]
  const out = replay(['body'], original, [
    { op: STRIP_MARKUP, column: 'body' },
    { op: STRIP_INVISIBLE },
  ])
  assert.deepEqual(out.rows, original)
})

// --- what an edit actually did, rather than what it was asked to do ----------

test('replay reports the cells each edit changed', () => {
  const out = replay(
    ['plan', 'note'],
    [['Premium', 'a'], ['premium', 'b'], [' Premium ', 'c'], ['Premium', 'd']],
    [
      { op: NORMALIZE, column: 'plan', from: ['Premium', 'premium'], to: 'Premium' },
      { op: TRIM },
    ],
  )
  // Two rows spell it differently; the third differs only by padding, which
  // normalise already settles, so trim finds nothing left to do on that column.
  assert.equal(out.applied[0].changed, 2)
  assert.equal(out.applied[1].changed, 0)
})

test('a later fix reports what it did, not what the check estimated', () => {
  // The case the estimate gets wrong: the check counted two blank cells, then
  // blanking the sentinels made a third, and the fill touched all three.
  const out = replay(
    ['city'],
    [['London'], [''], ['n/a'], ['']],
    [
      { op: BLANK_VALUES, column: 'city', forms: ['n/a'] },
      { op: FILL_MISSING, column: 'city', value: 'Unknown' },
    ],
  )
  assert.equal(out.applied[0].changed, 1)
  assert.equal(out.applied[1].changed, 3)
  assert.match(describe(out.applied[1] && { op: 'fill_missing', column: 'city', value: 'Unknown' }, 3),
    /filled 3 gaps/)
})

test('an edit that changes nothing says so', () => {
  const out = replay(['a'], [['x'], ['y']], [{ op: NORMALIZE, column: 'a', from: ['z'], to: 'w' }])
  assert.equal(out.applied[0].changed, 0)
})

test('dropping rows counts only the rows it dropped', () => {
  const out = replay(
    ['a'],
    [['x'], ['x'], ['y']],
    [{ op: DEDUPE }, { op: DROP_ROWS, rowIndices: [1, 2] }],
  )
  assert.equal(out.applied[0].changed, 1) // row 1 was the duplicate
  assert.equal(out.applied[1].changed, 1) // row 1 was already gone
})

// --- a computed value has to look like the column it lands in ----------------

test('a computed number is written the way the column writes numbers', () => {
  // Writing 2 into a column of 2.0 is not only untidy. The lookup that fills
  // the item from the price is keyed on the text, so "2" misses a table that
  // says "2.0" and the row is labelled Unknown when the file could name it.
  const out = replay(
    ['qty', 'price', 'total'],
    [['2', '2.0', '4.0'], ['3', '2.0', '6.0'], ['4', '2.0', ''], ['5', '3.0', '']],
    [{ op: FILL_FROM_FORMULA, column: 'total', left: 'qty', right: 'price', operation: 'product' }],
  )
  assert.deepEqual(out.rows.map((r) => r[2]), ['4.0', '6.0', '8.0', '15.0'])
})

test('a column of integers keeps its integers', () => {
  const out = replay(
    ['a', 'b', 'c'],
    [['2', '3', '6'], ['4', '5', '20'], ['6', '7', '']],
    [{ op: FILL_FROM_FORMULA, column: 'c', left: 'a', right: 'b', operation: 'product' }],
  )
  assert.equal(out.rows[2][2], '42')
})

test('a column that disagrees with itself is left to the plain number', () => {
  const out = replay(
    ['a', 'b', 'c'],
    [['2', '3', '6'], ['4', '5', '20.5'], ['1', '2', '2.25'], ['6', '7', '']],
    [{ op: FILL_FROM_FORMULA, column: 'c', left: 'a', right: 'b', operation: 'product' }],
  )
  assert.equal(out.rows[3][2], '42')
})
