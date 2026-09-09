// Scores Sift's one-click cleaning against the hand-cleaned reference for every
// archetype in benchmark/.
//
// Three numbers per dataset. Coverage is how much of the junk was removed:
// values a person would not accept in a finished file - markers meaning
// missing, numbers that will not parse, padding. Agreement is how often Sift's
// value for a cell matches the reference, over the cells the reference filled
// in. Damage is the one that is worth the most and flatters the least: of the
// cells that were already right in the dirty file, how many did Sift change
// into something the reference disagrees with.
//
// The reason damage is here is that the other two are not independent evidence.
// The faults in these files were injected by someone who knew which checks
// exist, so coverage measures whether the tool finds the faults it was built to
// find, and that is close to circular. Damage does not have that problem: it is
// measured over the cells nobody touched on purpose, so it cannot be raised by
// knowing the fault list. A tool that fixes everything and breaks nothing has
// to score well on it, and an over-eager one cannot.
//
//   python scripts/make_benchmark.py     # generate the pairs
//   python scripts/benchmark_audit.py    # run the audits
//   node scripts/benchmark.mjs           # score them

import { readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import { safeFixes } from '../src/autofix.js'
import { parseCsv } from '../src/csv.js'
import { replay } from '../src/edits.js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const DIR = join(ROOT, 'benchmark')

const MARKERS = new Set([
  'error', 'unknown', 'n/a', 'na', 'null', 'none', 'nil', 'nan', 'missing',
  '?', '-', '--', 'prefer not to say', '-999',
])

const norm = (v) => String(v ?? '').trim().toLowerCase()

function looksUnfinished(value) {
  const v = norm(value)
  if (v === '') return true
  if (MARKERS.has(v)) return true
  // A number wearing a costume: currency, separators, units, percent, brackets.
  if (/^[($]|[%]$|,\d{3}|\s(c|kg|km|m|cm|f)$|\)$/i.test(String(value).trim())) return true
  if (/^\s|\s$/.test(String(value))) return true
  return false
}

function junkCount(columns, rows) {
  let n = 0
  for (const row of rows) for (const cell of row) if (looksUnfinished(cell)) n += 1
  return n
}

function score(name) {
  const dirtyPath = join(DIR, `${name}_dirty.csv`)
  const idealPath = join(DIR, `${name}_ideal.csv`)
  const auditPath = join(DIR, `${name}_audit.json`)
  if (!existsSync(auditPath)) return null

  const dirty = parseCsv(readFileSync(dirtyPath, 'utf8'))
  const ideal = parseCsv(readFileSync(idealPath, 'utf8'))
  const audit = JSON.parse(readFileSync(auditPath, 'utf8'))

  const fixes = safeFixes(audit.issues)
  const cleaned = replay(dirty.columns, dirty.rows, fixes)

  // Measured against the reference rather than against zero. The hand-cleaned
  // file also contains the word "Unknown", because labelling an absence is the
  // right answer; scoring toward zero would penalise getting it right.
  const before = junkCount(dirty.columns, dirty.rows)
  const after = junkCount(cleaned.columns, cleaned.rows)
  const floor = junkCount(ideal.columns, ideal.rows)
  const removable = Math.max(before - floor, 0)
  const coverage = removable ? Math.min(Math.max(before - after, 0) / removable, 1) : 1

  // Agreement, cell by cell, on the columns both files still have. Compared
  // numerically where both sides look like numbers so 3.0 matches 3.
  const idealIndex = Object.fromEntries(ideal.columns.map((c, i) => [c, i]))
  const cleanIndex = Object.fromEntries(cleaned.columns.map((c, i) => [c, i]))
  const shared = cleaned.columns.filter((c) => c in idealIndex)

  // Compared exactly, not case-insensitively. Lowercasing both sides hides
  // exactly the faults the case checks exist to catch.
  const matches = (got, want) => {
    const a = Number(String(got).replace(/,/g, ''))
    const b = Number(String(want).replace(/,/g, ''))
    return Number.isFinite(a) && Number.isFinite(b)
      ? Math.abs(a - b) < 1e-6
      : String(got).trim() === String(want).trim()
  }

  const dirtyIndex = Object.fromEntries(dirty.columns.map((c, i) => [c, i]))
  let compared = 0
  let same = 0
  // Cells that already agreed with the reference before anything was applied.
  let wereRight = 0
  let broken = 0
  const perColumn = {}
  for (const column of shared) {
    let colSame = 0
    let colTotal = 0
    for (let r = 0; r < cleaned.rows.length && r < ideal.rows.length; r += 1) {
      const want = ideal.rows[r][idealIndex[column]]
      const got = cleaned.rows[r][cleanIndex[column]]
      if (norm(want) === '') continue // the reference left it blank too
      colTotal += 1
      if (matches(got, want)) colSame += 1

      // Rows are compared by position, so this only means anything while no
      // rows have been dropped above this one. sourceRows says which original
      // row each surviving row came from.
      const source = cleaned.sourceRows?.[r]
      if (source == null || dirtyIndex[column] == null) continue
      const before = dirty.rows[source]?.[dirtyIndex[column]]
      const wantBefore = ideal.rows[source]?.[idealIndex[column]]
      if (wantBefore == null || norm(wantBefore) === '') continue
      if (!matches(before, wantBefore)) continue
      wereRight += 1
      if (!matches(got, wantBefore)) broken += 1
    }
    compared += colTotal
    same += colSame
    if (colTotal) perColumn[column] = colSame / colTotal
  }

  return {
    name,
    fixes: fixes.length,
    coverage,
    agreement: compared ? same / compared : 1,
    worst: Object.entries(perColumn).sort((a, b) => a[1] - b[1])[0],
    junkBefore: before,
    junkAfter: after,
    damage: wereRight ? broken / wereRight : 0,
    wereRight,
    broken,
  }
}

const manifest = JSON.parse(readFileSync(join(DIR, 'manifest.json'), 'utf8'))
const results = Object.keys(manifest).map(score).filter(Boolean)

console.log('dataset              fixes  junk removed   agreement   damage   weakest column')
console.log('-------------------  -----  ------------   ---------   ------   --------------')
for (const r of results) {
  const worst = r.worst ? `${r.worst[0]} ${(r.worst[1] * 100).toFixed(0)}%` : '-'
  console.log(
    `${r.name.padEnd(19)}  ${String(r.fixes).padStart(5)}  ` +
      `${(r.coverage * 100).toFixed(0).padStart(4)}% (${r.junkBefore}\u2192${r.junkAfter})`.padEnd(15) +
      `${(r.agreement * 100).toFixed(1).padStart(7)}%   ` +
      `${(r.damage * 100).toFixed(2).padStart(5)}%   ${worst}`,
  )
}

const mean = (xs) => xs.reduce((a, b) => a + b, 0) / xs.length
const totalRight = results.reduce((a, r) => a + r.wereRight, 0)
const totalBroken = results.reduce((a, r) => a + r.broken, 0)
console.log(
  `\noverall: ${(mean(results.map((r) => r.coverage)) * 100).toFixed(1)}% of junk removed, ` +
    `${(mean(results.map((r) => r.agreement)) * 100).toFixed(1)}% agreement with the reference, ` +
    `${totalBroken} of ${totalRight.toLocaleString()} already-correct cells changed for the worse`,
)
console.log(
  '\nCoverage and agreement are measured against references written alongside the\n' +
    'faults, so they show that the tool finds what it was built to find. Damage is\n' +
    'the number to read sceptically for: it is measured over cells nothing was\n' +
    'aiming at, and no amount of knowing the fault list can improve it.',
)
