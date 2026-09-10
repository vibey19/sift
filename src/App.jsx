import { useEffect, useMemo, useState } from 'react'

import { ApiError, audit, profile as fetchProfile } from './api.js'
import { describeFixes, safeFixes } from './autofix.js'
import { parseCsv, toCsv } from './csv.js'
import { describe as describeEdit, replay } from './edits.js'
import { buildReport } from './report.js'
import ColumnMap from './components/ColumnMap.jsx'
import IssueDetail from './components/IssueDetail.jsx'
import IssueList from './components/IssueList.jsx'
import Summary from './components/Summary.jsx'
import ThemeToggle from './components/ThemeToggle.jsx'
import Upload from './components/Upload.jsx'

// Mirrors api/sift/config.py. Checked here so an oversized file is refused with
// a sentence instead of a 413 after a slow upload.
const MAX_ROWS = 50_000
const MAX_COLS = 200
// The request body limit is enforced in api.js, which is where the payload is
// compressed and its real size is therefore known.

export default function App({ handoff, onLeave }) {
  const [stage, setStage] = useState('empty')
  const [dataset, setDataset] = useState(null)
  const [columnProfile, setColumnProfile] = useState(null)
  const [mapping, setMapping] = useState({ label: null, split: null })
  const [result, setResult] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [edits, setEdits] = useState([])
  const [fixesApplied, setFixesApplied] = useState(false)
  const [error, setError] = useState(null)

  // A file chosen on the landing page arrives here already read. Consumed once,
  // by name, so a re-render cannot start the same audit twice.
  useEffect(() => {
    if (handoff && handoff.name !== dataset?.name) {
      onFile(handoff.name, handoff.text, handoff.hints ?? {})
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handoff])

  const reset = () => {
    setStage('empty')
    setDataset(null)
    setColumnProfile(null)
    setMapping({ label: null, split: null })
    setResult(null)
    setSelectedId(null)
    setEdits([])
    setFixesApplied(false)
    setError(null)
  }

  const onFile = async (name, text, hints = {}) => {
    setError(null)
    let parsed
    try {
      parsed = parseCsv(text)
    } catch {
      setError('That file could not be parsed as CSV.')
      return
    }
    if (!parsed.columns.length || !parsed.rows.length) {
      setError('That file has no rows in it.')
      return
    }
    if (parsed.rows.length > MAX_ROWS) {
      setError(
        `${parsed.rows.length.toLocaleString()} rows is over the ${MAX_ROWS.toLocaleString()} row limit. ` +
          'Sample the file down and audit the sample.',
      )
      return
    }
    if (parsed.columns.length > MAX_COLS) {
      setError(`${parsed.columns.length} columns is over the ${MAX_COLS} column limit.`)
      return
    }

    setDataset({ name, csv: text, encoding: hints.encoding ?? null, ...parsed })
    setEdits([])
    setStage('profiling')
    try {
      const body = await fetchProfile(text, { delimiter: parsed.delimiter })
      setColumnProfile(body)
      const names = new Set(body.columns.map((c) => c.name))
      const chosen = {
        label: names.has(hints.label) ? hints.label : null,
        split: names.has(hints.split) ? hints.split : null,
      }
      setMapping(chosen)
      // Straight into the audit. A label picker in front of the results is a
      // form standing between someone and the thing they came for, and all but three
      // of the twenty-nine checks do not need one.
      await run(text, chosen)
    } catch (err) {
      setError(messageFor(err))
      setStage('empty')
      setDataset(null)
    }
  }

  // Replayed on every render rather than kept as mutated state, so the parsed
  // file stays authoritative and undo is a pop.
  const current = useMemo(
    () => (dataset ? replay(dataset.columns, dataset.rows, edits) : null),
    [dataset, edits],
  )

  const run = async (csv, map) => {
    const source = typeof csv === 'string' ? csv : dataset.csv
    const chosen = map ?? mapping
    setStage('auditing')
    setError(null)
    try {
      const body = await audit(source, {
        labelColumn: chosen.label,
        splitColumn: chosen.split,
      })
      setResult(body)
      setSelectedId(body.issues[0]?.id ?? null)
      setEdits([])
      setFixesApplied(false)
      setStage('results')
    } catch (err) {
      setError(messageFor(err))
      setStage('mapping')
    }
  }

  const addEdit = (edit) => setEdits((log) => log.concat(edit))

  const fixes = result ? safeFixes(result.issues) : []
  const applyFixes = () => {
    setEdits((log) => log.concat(fixes))
    setFixesApplied(true)
  }
  const undo = () => setEdits((log) => log.slice(0, -1))

  const save = (contents, suffix, type) => {
    const blob = new Blob([contents], { type })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = dataset.name.replace(/\.(csv|tsv|txt)$/i, '') + suffix
    link.click()
    URL.revokeObjectURL(url)
  }

  const download = () =>
    save(
      toCsv(current.columns, current.rows, dataset.delimiter),
      '_cleaned.csv',
      'text/csv;charset=utf-8',
    )

  // Describes the data as it stands, edits included, so the report and the CSV
  // downloaded beside it never disagree.
  const downloadReport = () =>
    save(
      buildReport({ dataset, result, mapping, edits, current }),
      '_audit.md',
      'text/markdown;charset=utf-8',
    )

  // Re-auditing sends the edited rows back through the same endpoint. The
  // interesting case is dropping the leaked column and watching accuracy fall.
  const reaudit = () => {
    const cleaned = toCsv(current.columns, current.rows, dataset.delimiter)
    setDataset({ ...dataset, csv: cleaned, columns: current.columns, rows: current.rows })
    setEdits([])
    run(cleaned, mapping)
  }

  const selected = useMemo(
    () => result?.issues.find((i) => i.id === selectedId) ?? null,
    [result, selectedId],
  )

  return (
    <div className="app">
      <header className="app-header">
        <span className="wordmark">SIFT</span>
        <span className="label app-header-tag">dataset quality auditor</span>
        {/* A class rather than an inline style, because an inline gap cannot be
            overridden by a media query and this row has to reflow on a phone. */}
        <span className="app-header-right">
          {dataset && (
            <span className="label mono app-header-file">
              {dataset.name}
              {/* Said out loud only when it was not the obvious answer, because
                  a file that had to be guessed at is worth knowing about. */}
              {dataset.encoding && dataset.encoding !== 'utf-8' && ` · read as ${dataset.encoding}`}
            </span>
          )}
          <button className="link-back" onClick={onLeave}>
            ← back<span className="wide-only"> to the site</span>
          </button>
          <ThemeToggle />
        </span>
      </header>

      <main className="app-main">
        {error && (
          <div className="notice" data-tone="alarm" style={{ marginBottom: 16 }}>
            {error}
          </div>
        )}

        {stage === 'empty' && <Upload onFile={onFile} />}
        {stage === 'profiling' && (
          <Working
            title="Reading the file"
            note="Inferring column types."
            slowNote={
              'Waiting on the server, which sleeps when nobody has used it for a while ' +
              'and takes about a minute to start. This only happens on the first request; ' +
              'everything after it is immediate.'
            }
          />
        )}

        {(stage === 'mapping' || stage === 'auditing' || stage === 'results') && columnProfile && (
          <div style={{ marginBottom: 16 }}>
            <ColumnMap
              profile={columnProfile}
              label={mapping.label}
              split={mapping.split}
              onChange={setMapping}
              onRun={run}
              onReset={reset}
              busy={stage === 'auditing'}
            />
          </div>
        )}

        {stage === 'auditing' && (
          <Working
            title="Auditing"
            note={auditingNote(dataset?.rows.length ?? 0, Boolean(mapping.label))}
          />
        )}

        {stage === 'results' && result && (
          <>
            <Summary dataset={current} summary={result.summary} edits={edits.length} />

            {fixes.length > 0 && !fixesApplied && (
              <div className="autofix">
                <div>
                  <strong className="mono">
                    {fixes.length} {fixes.length === 1 ? 'fix can' : 'fixes can'} be applied safely
                  </strong>
                  <ul>
                    {describeFixes(fixes).map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                  <p className="autofix-note">
                    Nothing here needs a decision from you. Anything that does, such as
                    the leaked column, the contaminated rows or the model's relabelling, is
                    left alone.
                  </p>
                </div>
                <button className="button-primary" onClick={applyFixes}>
                  Apply {fixes.length === 1 ? 'it' : 'them'}
                </button>
              </div>
            )}

            {edits.length === 0 && (
              <div className="actions" style={{ marginTop: -4 }}>
                <button onClick={downloadReport}>Download the audit report</button>
              </div>
            )}

            {edits.length > 0 && (
              <div className="edit-log">
                <div className="label">
                  {edits.length} edit{edits.length === 1 ? '' : 's'} ·{' '}
                  {plural(dataset.rows.length - current.rows.length, 'row')} and{' '}
                  {plural(dataset.columns.length - current.columns.length, 'column')} removed
                </div>
                <ol>
                  {edits.map((edit, i) => (
                    <li key={i}>{describeEdit(edit, current.applied?.[i]?.changed)}</li>
                  ))}
                </ol>
                <p className="autofix-note" style={{ marginBottom: 12 }}>
                  The findings below still describe the file as you uploaded it. Re-auditing
                  runs every check again over the rows as they stand now, which is the only
                  way to see what the edits fixed and what they did not.
                </p>
                <div className="actions" style={{ marginBottom: 0 }}>
                  <button onClick={undo}>Undo the last edit</button>
                  <button className="button-primary" onClick={reaudit}>
                    Re-audit the cleaned data
                  </button>
                  <button onClick={downloadReport}>Download the audit report</button>
                  <button onClick={download}>Download cleaned CSV</button>
                </div>
              </div>
            )}
            {result.summary.skipped_checks.length > 0 && (
              <div className="notice" style={{ marginBottom: 16 }}>
                <div className="label" style={{ marginBottom: 6 }}>Not run</div>
                {result.summary.skipped_checks.map((s) => (
                  <div key={s.check} className="mono" style={{ fontSize: 13 }}>
                    {s.check}: {s.reason}
                  </div>
                ))}
              </div>
            )}
            <div className="columns">
              <IssueList issues={result.issues} selectedId={selectedId} onSelect={setSelectedId} />
              <IssueDetail
                issue={selected}
                dataset={dataset}
                current={current}
                onEdit={(edit) => addEdit(Array.isArray(edit) ? edit : [edit])}
              />
            </div>
          </>
        )}
      </main>
    </div>
  )
}

// A progress bar with nothing to report has to keep earning the wait, or ten
// seconds of it reads as a hang and sixty reads as broken. So it counts, and
// once it has been going longer than the work itself should take, it says what
// is actually happening instead: the API sleeps when idle and takes about a
// minute to wake, and a wait that has been explained is a different experience
// from the same wait in silence.
const SLOW_AFTER = 8

function Working({ title, note, slowNote }) {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setSeconds((s) => s + 1), 1000)
    return () => clearInterval(id)
  }, [])
  const slow = slowNote && seconds >= SLOW_AFTER

  return (
    <div className="loading panel">
      <p className="mono" style={{ margin: 0, fontSize: 15 }}>
        {title}
        <span aria-hidden> · {seconds}s</span>
      </p>
      <p className="label" style={{ marginTop: 8, textTransform: 'none', letterSpacing: 0 }}>
        {slow ? slowNote : note}
      </p>
      <div className="loading-bar" aria-hidden><i /></div>
    </div>
  )
}

// A progress bar that cannot say how far along it is has to say something else,
// or twenty seconds of it reads as a hang. The slow part is named, and so is
// roughly how long it should take, because a number that turns out to be right
// is what makes waiting feel like waiting rather than like failure.
function auditingNote(rows, hasLabel) {
  if (!hasLabel) {
    return `Running twenty-nine checks over ${rows.toLocaleString()} rows.`
  }
  // No second count. There was one, extrapolated from how long this takes on a
  // developer machine, and it was wrong by more than an order of magnitude on a
  // small hosted instance: five seconds promised, a minute delivered. A number
  // that turns out to be wrong is worse than no number, because the wait then
  // reads as a fault rather than as work. What the wait is for is true wherever
  // it runs.
  return (
    `Cross-validating a model over ${rows.toLocaleString()} rows, so that every row is ` +
    'scored by one that never saw it. This is the slowest part of the audit and the ' +
    'only part that grows with the size of the file.'
  )
}

function plural(n, noun) {
  return `${n.toLocaleString()} ${noun}${n === 1 ? '' : 's'}`
}

function messageFor(err) {
  if (err instanceof ApiError) return err.message
  return 'Something went wrong running the audit.'
}
