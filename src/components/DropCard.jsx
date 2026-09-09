import { useRef, useState } from 'react'

import { ACCEPTS, SAMPLES, readSample } from '../samples.js'

// The auditor's entry point, on the landing page. Dropping a file here hands it
// straight to the audit view rather than sending anyone to a second page and
// asking them to find the upload control again.
export default function DropCard({ onOpen }) {
  const [dragging, setDragging] = useState(false)
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)
  const input = useRef(null)

  const take = async (file) => {
    setError(null)
    if (!ACCEPTS.test(file.name)) {
      setError(`${file.name} is not a CSV or TSV. Sift reads those two formats.`)
      return
    }
    onOpen({ name: file.name, text: await file.text() })
  }

  const loadSample = async (sample) => {
    setError(null)
    setBusy(sample.name)
    try {
      onOpen(await readSample(sample))
    } catch {
      setError(`Could not load ${sample.name}.`)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="start">
      <div
        className="start-drop"
        data-active={dragging}
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          if (e.dataTransfer.files[0]) take(e.dataTransfer.files[0])
        }}
      >
        <p className="start-title">Drop a CSV here</p>
        <p className="start-sub">or</p>
        <button className="btn btn-primary" onClick={() => input.current?.click()}>
          Choose a file
        </button>
        <input
          ref={input}
          type="file"
          accept=".csv,.tsv,.txt,text/csv"
          hidden
          onChange={(e) => e.target.files[0] && take(e.target.files[0])}
        />
        <p className="start-note">
          Parsed in your browser. Audited by a stateless function. Never stored.
        </p>
      </div>

      <div className="start-samples">
        <p className="label" style={{ marginBottom: 8 }}>Or try a broken one</p>
        {SAMPLES.map((sample) => (
          <button
            key={sample.name}
            className="start-sample"
            onClick={() => loadSample(sample)}
            disabled={busy !== null}
          >
            <strong>{busy === sample.name ? 'loading...' : sample.name}</strong>
            <span>{sample.wrong}</span>
          </button>
        ))}
      </div>

      {error && (
        <p className="start-error mono">{error}</p>
      )}
    </div>
  )
}
