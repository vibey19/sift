import { useState } from 'react'

import demo from '../demo.json'

const TAGS = { high: '[HIGH]', medium: '[MED]', low: '[LOW]' }

// Real output from auditing the sample dataset, trimmed by scripts/make_demo.py.
// Writing plausible-looking findings by hand would have been easier and would
// have made the page a lie.
export default function Demo() {
  const [selected, setSelected] = useState(demo.issues[0].id)
  const issue = demo.issues.find((i) => i.id === selected) ?? demo.issues[0]

  return (
    <section className="section demo" id="demo">
      <div className="wrap">
        <p className="eyebrow" style={{ color: 'var(--lime)' }}>A real run</p>
        <h2>This is what it says about the sample dataset.</h2>
        <p className="lede" style={{ marginBottom: 34 }}>
          Every word below came out of the tool auditing{' '}
          <span className="mono">{demo.dataset}</span>. Click a finding to read it.
        </p>

        <div className="demo-frame">
          <div className="demo-bar">
            <Stat label="Rows" value={demo.n_rows.toLocaleString()} />
            <Stat label="Columns" value={demo.n_cols} />
            <Stat label="High" value={demo.high} tone="alarm" />
            <Stat label="Medium" value={demo.medium} />
            <Stat label="Low" value={demo.low} />
            <Stat label="CV accuracy" value={demo.cv_accuracy.toFixed(3)} />
          </div>

          <div className="demo-body">
            <div className="demo-list">
              {demo.issues.map((item) => (
                <button
                  key={item.id}
                  className="issue"
                  data-severity={item.severity}
                  data-selected={item.id === selected}
                  onClick={() => setSelected(item.id)}
                >
                  <span className="issue-tag">
                    {TAGS[item.severity]}
                    {item.column ? ` ${item.column}` : ''}
                  </span>
                  <span className="issue-title">{item.title}</span>
                </button>
              ))}
            </div>

            <div className="demo-detail">
              <p className="label">{issue.check}</p>
              <h3>{issue.title}</h3>
              <p>{issue.detail}</p>
              <p className="demo-rows">
                {issue.row_indices.length
                  ? `${issue.total_affected.toLocaleString()} rows · ${issue.row_indices.join(', ')} ...`
                  : `applies to the whole '${issue.column}' column`}
              </p>
            </div>
          </div>
        </div>

        <p className="demo-note">
          The full run finds {demo.high + demo.medium + demo.low} issues across{' '}
          {demo.rows_affected.toLocaleString()} rows. Open the auditor to work through them.
        </p>
      </div>
    </section>
  )
}

function Stat({ label, value, tone }) {
  return (
    <div className="stat" data-tone={tone}>
      <div className="label">{label}</div>
      <div className="stat-value">{value}</div>
    </div>
  )
}
