import { DEDUPE, DROP_COLUMN, DROP_ROWS, NORMALIZE, RELABEL } from '../edits.js'
import RowTable from './RowTable.jsx'

export default function IssueDetail({ issue, dataset, current, onEdit }) {
  if (!issue) {
    return (
      <div className="detail">
        <p className="empty-detail">Pick an issue to see what it found and why it matters.</p>
      </div>
    )
  }

  const cv = issue.evidence?.cv_accuracy
  const action = actionFor(issue)
  const live = issue.row_indices.filter((i) => !current.droppedRows.has(i))
  const alreadyDone =
    (action?.op === DROP_COLUMN && current.droppedColumns.has(issue.column)) ||
    (issue.row_indices.length > 0 && live.length === 0)

  return (
    <div className="detail">
      <p className="label">{issue.check}</p>
      <h2>{issue.title}</h2>
      <p>{issue.detail}</p>

      {issue.evidence?.low_confidence && (
        <div className="notice" data-tone="alarm" style={{ marginBottom: 14 }}>
          The model behind these flags scored {cv.toFixed(2)} in cross-validation. It cannot
          model this task, so treat the list as low confidence rather than a set of corrections.
        </div>
      )}

      {action && (
        <div className="actions">
          {alreadyDone ? (
            <span className="done">Applied. Undo it from the edit log above.</span>
          ) : (
            <button className="button-primary" onClick={() => onEdit(action.edit(live))}>
              {action.label(live)}
            </button>
          )}
        </div>
      )}

      {issue.row_indices.length === 0 ? (
        <>
          <div className="label" style={{ marginBottom: 6 }}>Applies to</div>
          <p className="mono" style={{ margin: 0 }}>
            {issue.column ? `the whole '${issue.column}' column` : 'the whole dataset'}
          </p>
        </>
      ) : (
        <>
          <div className="label" style={{ marginBottom: 6 }}>
            {issue.total_affected.toLocaleString()} affected rows
            {issue.row_indices.length < issue.total_affected &&
              ` · first ${issue.row_indices.length.toLocaleString()} shown`}
          </div>
          <RowTable
            columns={dataset.columns}
            rows={dataset.rows}
            indices={issue.row_indices}
            highlight={issue.column}
            dropped={current.droppedRows}
            droppedColumns={current.droppedColumns}
          />
        </>
      )}
    </div>
  )
}

// The server already said what it thinks should happen to each finding. This
// turns that into the one button that does it.
function actionFor(issue) {
  switch (issue.suggested_action) {
    case 'drop_rows':
      return {
        op: DROP_ROWS,
        label: (rows) => `Drop ${rows.length.toLocaleString()} rows`,
        edit: (rows) => ({ op: DROP_ROWS, rowIndices: rows }),
      }
    case 'dedupe':
      return {
        op: DEDUPE,
        label: () => 'Remove the duplicate copies',
        edit: () => ({ op: DEDUPE }),
      }
    case 'drop_column':
      return {
        op: DROP_COLUMN,
        label: () => `Drop the '${issue.column}' column`,
        edit: () => ({ op: DROP_COLUMN, column: issue.column }),
      }
    case 'relabel': {
      // R1 hands back a predicted label per row, so each row moves to its own
      // value rather than all of them to one.
      const predictions = Object.fromEntries(
        (issue.evidence?.rows ?? []).map((r) => [r.index, r.predicted]),
      )
      if (!Object.keys(predictions).length) return null
      return {
        op: RELABEL,
        label: (rows) =>
          `Relabel ${rows.filter((r) => r in predictions).length} rows to the model's answer`,
        edit: (rows) => ({
          op: RELABEL,
          column: issue.column,
          values: Object.fromEntries(
            rows.filter((r) => r in predictions).map((r) => [r, predictions[r]]),
          ),
        }),
      }
    }
    case 'normalize_values': {
      const canonical = issue.evidence?.canonical ?? {}
      const entries = Object.entries(canonical)
      if (!entries.length) return null
      return {
        op: NORMALIZE,
        label: () => `Normalise ${entries.length} value${entries.length === 1 ? '' : 's'}`,
        // One edit per canonical form, applied in sequence.
        edit: () => entries.map(([to, from]) => ({ op: NORMALIZE, column: issue.column, from, to })),
      }
    }
    default:
      return null
  }
}
