export default function IssueDetail({ issue }) {
  if (!issue) {
    return (
      <div className="detail">
        <p className="empty-detail">Pick an issue to see what it found and why it matters.</p>
      </div>
    )
  }

  const cv = issue.evidence?.cv_accuracy
  return (
    <div className="detail">
      <p className="label">{issue.check}</p>
      <h2>{issue.title}</h2>
      <p>{issue.detail}</p>

      {issue.evidence?.low_confidence && (
        <div className="notice" data-tone="alarm" style={{ marginBottom: 14 }}>
          The model behind these flags scored {cv.toFixed(2)} in cross-validation. It cannot
          model this task, so treat the list as low confidence rather than a set of
          corrections.
        </div>
      )}

      {issue.row_indices.length === 0 ? (
        // Leakage, constant and redundant columns are properties of a column, not
        // of particular rows. Showing a row count here reads as a mistake.
        <>
          <div className="label" style={{ marginBottom: 6 }}>Applies to</div>
          <p className="mono" style={{ margin: 0 }}>
            {issue.column ? `the whole '${issue.column}' column` : 'the whole dataset'}
          </p>
        </>
      ) : (
        <>
          <div className="label" style={{ marginBottom: 6 }}>Affected rows</div>
          <p className="mono" style={{ margin: 0 }}>
            {issue.total_affected.toLocaleString()}
            {issue.row_indices.length < issue.total_affected &&
              ` (first ${issue.row_indices.length.toLocaleString()} listed)`}
          </p>
          <p className="mono" style={{ color: 'var(--ink-soft)', marginTop: 8 }}>
            rows {issue.row_indices.slice(0, 12).join(', ')}
            {issue.row_indices.length > 12 ? ' ...' : ''}
          </p>
        </>
      )}
    </div>
  )
}
