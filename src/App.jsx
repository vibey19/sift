import { useEffect, useMemo, useState } from 'react'

import { ApiError, audit, profile as fetchProfile } from './api.js'
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
// Vercel caps a serverless request body at 4.5MB.
const MAX_BYTES = 4.5 * 1024 * 1024

export default function App({ handoff, onLeave }) {
  const [stage, setStage] = useState('empty')
  const [dataset, setDataset] = useState(null)
  const [columnProfile, setColumnProfile] = useState(null)
  const [mapping, setMapping] = useState({ label: null, split: null })
  const [result, setResult] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [edits, setEdits] = useState([])
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
    if (new Blob([text]).size > MAX_BYTES) {
      setError('That file is over 4.5MB, which is the serverless request limit. Sample it down.')
      return
    }

    setDataset({ name, csv: text, ...parsed })
    setEdits([])
    setStage('profiling')
    try {
      const body = await fetchProfile(text, { delimiter: parsed.delimiter })
      setColumnProfile(body)
      const names = new Set(body.columns.map((c) => c.name))
      setMapping({
        label: names.has(hints.label) ? hints.label : null,
        split: names.has(hints.split) ? hints.split : null,
      })
      setStage('mapping')
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

  const run = async (csv = dataset.csv, keepEdits = false) => {
    setStage('auditing')
    setError(null)
    try {
      const body = await audit(csv, {
        labelColumn: mapping.label,
        splitColumn: mapping.split,
      })
      setResult(body)
      setSelectedId(body.issues[0]?.id ?? null)
      if (!keepEdits) setEdits([])
      setStage('results')
    } catch (err) {
      setError(messageFor(err))
      setStage('mapping')
    }
  }

  const addEdit = (edit) => setEdits((log) => log.concat(edit))
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
    run(cleaned)
  }

  const selected = useMemo(
    () => result?.issues.find((i) => i.id === selectedId) ?? null,
    [result, selectedId],
  )

  return (
    <div className="app">
      <header className="app-header">
        <span className="wordmark">SIFT</span>
        <span className="label">dataset quality auditor</span>
        <span style={{ marginLeft: 'auto', display: 'flex', gap: 16, alignItems: 'baseline' }}>
          {dataset && (
            <span className="label mono" style={{ textTransform: 'none' }}>{dataset.name}</span>
          )}
          <button className="link-back" onClick={onLeave}>← back to the site</button>
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
        {stage === 'profiling' && <Working title="Reading the file" note="Inferring column types." />}

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
            note="Cross-validating a model over your rows. On a large file this takes a while."
          />
        )}

        {stage === 'results' && result && (
          <>
            <Summary dataset={current} summary={result.summary} edits={edits.length} />

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
                    <li key={i}>{describeEdit(edit)}</li>
                  ))}
                </ol>
                <div className="actions" style={{ marginBottom: 0 }}>
                  <button onClick={undo}>Undo the last edit</button>
                  <button onClick={reaudit}>Re-audit the cleaned data</button>
                  <button onClick={downloadReport}>Download the audit report</button>
                  <button className="button-primary" onClick={download}>
                    Download cleaned CSV
                  </button>
                </div>
              </div>
            )}
            {result.summary.skipped_checks.length > 0 && (
              <div className="notice" style={{ marginBottom: 16 }}>
                <div className="label" style={{ marginBottom: 6 }}>Not run</div>
                {result.summary.skipped_checks.map((s) => (
                  <div key={s.check} className="mono" style={{ fontSize: 13 }}>
                    {s.check} — {s.reason}
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

function Working({ title, note }) {
  const [seconds, setSeconds] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setSeconds((s) => s + 1), 1000)
    return () => clearInterval(id)
  }, [])

  return (
    <div className="loading panel">
      <p className="mono" style={{ margin: 0, fontSize: 15 }}>
        {title}
        <span aria-hidden> · {seconds}s</span>
      </p>
      <p className="label" style={{ marginTop: 8, textTransform: 'none', letterSpacing: 0 }}>
        {note}
      </p>
      <div className="loading-bar" aria-hidden><i /></div>
    </div>
  )
}

function plural(n, noun) {
  return `${n.toLocaleString()} ${noun}${n === 1 ? '' : 's'}`
}

function messageFor(err) {
  if (err instanceof ApiError) return err.message
  return 'Something went wrong running the audit.'
}
