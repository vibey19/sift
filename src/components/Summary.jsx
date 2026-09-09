export default function Summary({ dataset, summary }) {
  const cv = summary.cv_accuracy
  // Printed next to the flags rather than hidden. A list of suspicious rows
  // means nothing until you know whether the model could learn the task at all.
  const weak = cv != null && cv < 0.6

  return (
    <div className="summary">
      <Stat label="Rows" value={dataset.rows.length.toLocaleString()} />
      <Stat label="Columns" value={dataset.columns.length} />
      <Stat label="High" value={summary.high} tone={summary.high ? 'alarm' : null} />
      <Stat label="Medium" value={summary.medium} />
      <Stat label="Low" value={summary.low} />
      <Stat label="Rows affected" value={summary.rows_affected.toLocaleString()} />
      <Stat
        label={weak ? 'CV accuracy · weak' : 'CV accuracy'}
        value={cv == null ? 'n/a' : cv.toFixed(3)}
        tone={weak ? 'warn' : null}
        title={
          cv == null
            ? 'No label column was chosen, so no model was trained.'
            : 'Accuracy of the cross-validated model that produced the mislabel flags.'
        }
      />
    </div>
  )
}

function Stat({ label, value, tone, title }) {
  return (
    <div className="stat" data-tone={tone ?? undefined} title={title}>
      <div className="label">{label}</div>
      <div className="stat-value">{value}</div>
    </div>
  )
}
