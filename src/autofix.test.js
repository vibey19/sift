import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

import { safeFixes } from './autofix.js'
import { parseCsv } from './csv.js'
import { replay } from './edits.js'

const dataset = (() => {
  const source = readFileSync(new URL('../public/samples/churn_dirty.csv', import.meta.url), 'utf8')
  return parseCsv(source)
})()
const audit = JSON.parse(
  readFileSync(new URL('./fixtures/audit_churn.json', import.meta.url), 'utf8'),
)

test('picks up every unambiguous fix on the sample', () => {
  const ops = new Set(safeFixes(audit.issues).map((e) => e.op))
  for (const expected of [
    'trim',
    'blank_values',
    'normalize_values',
    'fill_missing',
    'drop_column',
    'dedupe',
    'drop_rows',
  ]) {
    assert.ok(ops.has(expected), `${expected} was not offered`)
  }
})

test('fixes come back in an order that lets them build on each other', () => {
  // Sentinels have to be blanked before a gap can be filled, and rows can only
  // be deduplicated once every value has settled.
  const ops = safeFixes(audit.issues).map((e) => e.op)
  const at = (op) => ops.indexOf(op)

  assert.ok(at('trim') < at('blank_values'), 'trim must run first')
  assert.ok(at('blank_values') < at('fill_missing'), 'blank before filling gaps')
  assert.ok(at('fill_missing') < at('dedupe'), 'dedupe last, once values have settled')
  assert.ok(at('dedupe') < at('drop_rows'), 'drop rows after deduplicating')
})

test('never touches anything that needs a judgement call', () => {
  const edits = safeFixes(audit.issues)
  const columns = edits.map((e) => e.column).filter(Boolean)

  // The leaked column, the identifiers and the contaminated rows are the whole
  // point of the tool. Removing them silently would be answering for the user.
  assert.ok(!columns.includes('cancellation_reason'))
  assert.ok(!columns.includes('customer_id'))
  assert.ok(!columns.includes('email'))
  assert.ok(!edits.some((e) => e.op === 'relabel'))
  // Numbers are never filled with a label, only categories.
  const filled = edits.filter((e) => e.op === 'fill_missing').map((e) => e.column)
  assert.ok(!filled.includes('tenure_months') && !filled.includes('monthly_charges'))

  const contaminated = audit.issues.find((i) => i.check === 'D4_train_test_overlap').row_indices
  const droppedRows = edits.flatMap((e) => e.rowIndices ?? [])
  assert.equal(droppedRows.filter((r) => contaminated.includes(r)).length, 0)
})

test('applying them leaves the data smaller and cleaner', () => {
  const before = replay(dataset.columns, dataset.rows, [])
  const after = replay(dataset.columns, dataset.rows, safeFixes(audit.issues))

  assert.ok(after.rows.length < before.rows.length, 'no rows were removed')
  assert.ok(after.columns.length < before.columns.length, 'no columns were removed')

  // The duplicates are gone.
  const key = (r) => r.join('')
  assert.equal(new Set(after.rows.map(key)).size, after.rows.length)

  // And the spelling variants have collapsed to one form.
  const planAt = after.columns.indexOf('plan')
  const spellings = new Set(after.rows.map((r) => r[planAt]).filter((v) => /premium/i.test(v)))
  assert.equal(spellings.size, 1, `plan still has ${[...spellings].join(', ')}`)
})

test('every fix carries a sentence saying what it did', () => {
  for (const edit of safeFixes(audit.issues)) {
    assert.ok(edit.label && edit.label.length > 8, JSON.stringify(edit))
  }
})

test('a clean dataset produces no fixes', () => {
  assert.deepEqual(safeFixes([]), [])
  assert.deepEqual(safeFixes(audit.issues.filter((i) => i.check === 'C10_leakage')), [])
})

test('a check with nothing behind it does not become an empty edit', () => {
  const hollow = [
    { check: 'C1_sparse_rows', row_indices: [], total_affected: 0, evidence: {} },
    { check: 'C5_categorical_inconsistency', column: 'x', evidence: { canonical: {} } },
  ]
  assert.deepEqual(safeFixes(hollow), [])
})

test('the fixes are ordinary edits, so undo still works', () => {
  const edits = safeFixes(audit.issues)
  const full = replay(dataset.columns, dataset.rows, edits)
  const undone = replay(dataset.columns, dataset.rows, edits.slice(0, -1))
  assert.notDeepEqual(full.rows.length + full.columns.length, undone.rows.length + undone.columns.length)

  const none = replay(dataset.columns, dataset.rows, [])
  assert.equal(none.rows.length, dataset.rows.length)
})
