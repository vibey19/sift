import { useEffect, useMemo, useState } from 'react'

import { ApiError, audit, profile as fetchProfile } from './api.js'
import { parseCsv } from './csv.js'
import ColumnMap from './components/ColumnMap.jsx'
import IssueDetail from './components/IssueDetail.jsx'
import IssueList from './components/IssueList.jsx'
import Summary from './components/Summary.jsx'
import Upload from './components/Upload.jsx'

// Mirrors api/sift/config.py. Checked here so an oversized file is refused with
// a sentence instead of a 413 after a slow upload.
const MAX_ROWS = 50_000
const MAX_COLS = 200
// Vercel caps a serverless request body at 4.5MB.
const MAX_BYTES = 4.5 * 1024 * 1024

export default function App() {
  const [stage, setStage] = useState('empty')
  const [dataset, setDataset] = useState(null)
  const [columnProfile, setColumnProfile] = useState(null)
  const [mapping, setMapping] = useState({ label: null, split: null })
  const [result, setResult] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [error, setError] = useState(null)

  const reset = () => {
    setStage('empty')
    setDataset(null)
    setColumnProfile(null)
    setMapping({ label: null, split: null })
    setResult(null)
    setSelectedId(null)
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

  const run = async () => {
    setStage('auditing')
    setError(null)
    try {
      const body = await audit(dataset.csv, {
        labelColumn: mapping.label,
        splitColumn: mapping.split,
      })
      setResult(body)
      setSelectedId(body.issues[0]?.id ?? null)
      setStage('results')
    } catch (err) {
      setError(messageFor(err))
      setStage('mapping')
    }
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
        {dataset && (
          <span className="label mono" style={{ marginLeft: 'auto', textTransform: 'none' }}>
            {dataset.name}
          </span>
        )}
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
            <Summary dataset={dataset} summary={result.summary} />
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
              <IssueDetail issue={selected} />
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

function messageFor(err) {
  if (err instanceof ApiError) return err.message
  return 'Something went wrong running the audit.'
}
