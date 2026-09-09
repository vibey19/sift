// The one-click path.
//
// A fix counts as safe when applying it without being asked cannot lose
// something the user might have wanted. Deduplicating keeps the first copy of
// each record. Dropping a column whose every row is identical removes no
// information. Normalising four spellings of "Premium" is a rename, not a
// deletion. Rows that are more than half empty are a broken import rather than
// thin data, which is the one row-dropping fix included here.
//
// Everything requiring judgement is deliberately excluded: dropping a leaked
// column, dropping contaminated rows, accepting the model's relabelling, and
// removing identifier columns. Those change what the data means, and the user
// should be the one deciding.

import { DEDUPE, DROP_COLUMN, DROP_ROWS, NORMALIZE } from './edits.js'

const SAFE = {
  C5_categorical_inconsistency: (issue) =>
    Object.entries(issue.evidence?.canonical ?? {}).map(([to, from]) => ({
      op: NORMALIZE,
      column: issue.column,
      from,
      to,
      label: `normalise ${from.length} spellings in '${issue.column}'`,
    })),

  D1_exact_duplicates: (issue) => [
    {
      op: DEDUPE,
      label: `remove ${issue.total_affected - (issue.evidence?.n_groups ?? 0)} duplicate rows`,
    },
  ],

  C2_constant: (issue) => [
    {
      op: DROP_COLUMN,
      column: issue.column,
      label: `drop '${issue.column}', which never varies`,
    },
  ],

  C1_sparse_rows: (issue) => [
    {
      op: DROP_ROWS,
      rowIndices: issue.row_indices,
      label: `drop ${issue.row_indices.length} rows that are more than half empty`,
    },
  ],
}

export function safeFixes(issues = []) {
  const edits = []
  for (const issue of issues) {
    const build = SAFE[issue.check]
    if (!build) continue
    for (const edit of build(issue)) {
      // A check can fire with nothing actionable behind it, which should not
      // become an edit that does nothing and still occupies the undo stack.
      if (edit.op === NORMALIZE && !edit.from?.length) continue
      if (edit.op === DROP_ROWS && !edit.rowIndices?.length) continue
      edits.push(edit)
    }
  }
  return edits
}

export function describeFixes(edits) {
  return edits.map((edit) => edit.label).filter(Boolean)
}
