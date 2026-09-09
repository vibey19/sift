import { useRef, useState } from 'react'

const SAMPLES = [
  {
    name: 'churn_dirty.csv',
    path: '/samples/churn_dirty.csv',
    label: 'churned',
    split: 'split',
    wrong: 'A column populated only after customers left, 25 records sitting in both train and test, and 40 labels flipped.',
  },
  {
    name: 'reviews_dirty.csv',
    path: '/samples/reviews_dirty.csv',
    label: 'sentiment',
    split: 'split',
    wrong: 'Three sentiment classes written nine different ways, plus re-posted reviews with one figure changed.',
  },
]

export default function Upload({ onFile, disabled }) {
  const [dragging, setDragging] = useState(false)
  const [error, setError] = useState(null)
  const input = useRef(null)

  const take = async (file) => {
    setError(null)
    if (!/\.(csv|tsv|txt)$/i.test(file.name)) {
      setError(`${file.name} is not a CSV or TSV. Sift reads those two formats only.`)
      return
    }
    onFile(file.name, await file.text())
  }

  const loadSample = async (sample) => {
    setError(null)
    try {
      const response = await fetch(sample.path)
      if (!response.ok) throw new Error(String(response.status))
      onFile(sample.name, await response.text(), { label: sample.label, split: sample.split })
    } catch {
      setError(`Could not load ${sample.name}.`)
    }
  }

  return (
    <div>
      <p className="label" style={{ marginBottom: 10 }}>Start with a sample</p>
      <div className="sample-grid">
        {SAMPLES.map((sample) => (
          <button
            key={sample.name}
            className="sample"
            onClick={() => loadSample(sample)}
            disabled={disabled}
          >
            <strong>{sample.name}</strong>
            <span>{sample.wrong}</span>
          </button>
        ))}
      </div>

      <p className="label" style={{ margin: '26px 0 10px' }}>Or audit your own</p>
      <div
        className="drop"
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
        <p style={{ margin: '0 0 14px' }}>Drop a CSV or TSV here.</p>
        <button onClick={() => input.current?.click()} disabled={disabled}>
          Choose a file
        </button>
        <input
          ref={input}
          type="file"
          accept=".csv,.tsv,.txt,text/csv"
          hidden
          onChange={(e) => e.target.files[0] && take(e.target.files[0])}
        />
        <p className="label" style={{ marginTop: 16 }}>
          Nothing is stored. The file is audited and forgotten.
        </p>
      </div>

      {error && (
        <div className="notice" data-tone="alarm" style={{ marginTop: 16 }}>
          {error}
        </div>
      )}
    </div>
  )
}
