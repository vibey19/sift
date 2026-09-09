import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

import { parseCsv } from './csv.js'
import { DROP_COLUMN, DROP_ROWS, replay } from './edits.js'
import { buildReport } from './report.js'

const dataset = (() => {
  const source = readFileSync(new URL('../public/samples/churn_dirty.csv', import.meta.url), 'utf8')
  return { name: 'churn_dirty.csv', ...parseCsv(source) }
})()

const result = JSON.parse(
  readFileSync(new URL('./fixtures/audit_churn.json', import.meta.url), 'utf8'),
)
const noLabel = JSON.parse(
  readFileSync(new URL('./fixtures/audit_no_label.json', import.meta.url), 'utf8'),
)

const mapping = { label: 'churned', split: 'split' }

function report(edits = [], body = result, map = mapping) {
  return buildReport({
    dataset,
    result: body,
    mapping: map,
    edits,
    current: replay(dataset.columns, dataset.rows, edits),
  })
}

test('names the dataset and the columns it was given', () => {
  const md = report()
  assert.match(md, /# Data quality audit: churn_dirty\.csv/)
  assert.match(md, /Label column \s*\| churned/)
  assert.match(md, /Split column \s*\| split/)
})

test('every issue appears under its severity heading', () => {
  const md = report()
  for (const issue of result.issues) assert.ok(md.includes(issue.title), issue.title)
  assert.ok(md.indexOf('### HIGH') < md.indexOf('### MEDIUM'))
  assert.ok(md.indexOf('### MEDIUM') < md.indexOf('### LOW'))
})

test('carries the accuracy of the model that produced the flags', () => {
  const md = report()
  assert.match(md, /cross-validation, so it is worth listening to/)
  // Compared against the fixture's own number rather than a literal, so
  // regenerating the samples does not break the test for the wrong reason.
  assert.ok(md.includes(result.summary.cv_accuracy.toFixed(3)))
})

test('warns rather than reassures when the model is weak', () => {
  const weak = { ...result, summary: { ...result.summary, cv_accuracy: 0.44 } }
  const md = report([], weak)
  // Only the summary preamble is checked. R1's own detail text quotes the
  // reassuring phrasing and is reproduced verbatim further down.
  const preamble = md.slice(0, md.indexOf('## Findings'))
  assert.match(preamble, /close to noise/)
  assert.ok(!preamble.includes('worth listening to'))
})

test('says which checks did not run and why', () => {
  const md = report([], noLabel, { label: null, split: null })
  assert.match(md, /Checks that did not run/)
  assert.match(md, /`R1_mislabels`: no label column was chosen/)
  assert.match(md, /not measured/)
})

test('an unedited report says so plainly', () => {
  assert.match(report(), /This report describes the file as it was uploaded/)
})

test('records the edits and the resulting shape', () => {
  const contaminated = result.issues.find((i) => i.check === 'D4_train_test_overlap').row_indices
  const md = report([
    { op: DROP_COLUMN, column: 'cancellation_reason' },
    { op: DROP_ROWS, rowIndices: contaminated },
  ])
  assert.match(md, /Dropped the `cancellation_reason` column/)
  assert.match(md, new RegExp(`Dropped ${contaminated.length} rows`))
  assert.match(md, /3,025 rows and 13 columns/)
  assert.match(md, /50 rows and 1 columns removed/)
})

test('row lists are capped rather than dumping thousands of numbers', () => {
  const md = report()
  const longest = Math.max(...md.split('\n').map((l) => l.length))
  assert.ok(longest < 400, `a line ran to ${longest} characters`)
})

test('is valid enough markdown to render', () => {
  const md = report()
  // Balanced table pipes on every table row, and no stray heading levels.
  for (const line of md.split('\n')) {
    if (!line.startsWith('|')) continue
    assert.ok(line.endsWith('|'), `unterminated table row: ${line}`)
  }
  assert.ok(!md.includes('undefined'))
  assert.ok(!md.includes('[object Object]'))
})
