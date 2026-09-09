const TAGS = { high: '[HIGH]', medium: '[MED]', low: '[LOW]' }

export default function IssueList({ issues, selectedId, onSelect }) {
  if (!issues.length) {
    return (
      <div className="issue-list">
        <p className="empty-detail">Nothing flagged. That is unusual enough to be worth a second look.</p>
      </div>
    )
  }
  return (
    <div className="issue-list" role="list">
      {issues.map((issue) => (
        <button
          key={issue.id}
          role="listitem"
          className="issue"
          data-severity={issue.severity}
          data-selected={issue.id === selectedId}
          onClick={() => onSelect(issue.id)}
        >
          <span className="issue-tag">
            {TAGS[issue.severity]}
            {issue.column ? ` ${issue.column}` : ''}
          </span>
          <span className="issue-title">{issue.title}</span>
        </button>
      ))}
    </div>
  )
}
