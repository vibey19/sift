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

import {
  BLANK_VALUES,
  DEDUPE,
  DROP_COLUMN,
  DROP_ROWS,
  FILL_FROM_COLUMN,
  FILL_FROM_FORMULA,
  FILL_MISSING,
  NORMALIZE,
  NORMALIZE_BOOLEAN,
  REFORMAT_DATE,
  REFORMAT_NUMBER,
  STRIP_INVISIBLE,
  STRIP_MARKUP,
  TRIM,
} from './edits.js'

// Order is not cosmetic. Sentinels have to be blanked before a gap can be
// filled, a gap has to be filled before the row stops looking half empty, and
// deduplication has to run after every value has settled or it compares rows
// that are about to change.
const ORDER = [
  STRIP_INVISIBLE,
  STRIP_MARKUP,
  TRIM,
  BLANK_VALUES,
  REFORMAT_NUMBER,
  REFORMAT_DATE,
  NORMALIZE_BOOLEAN,
  NORMALIZE,
  FILL_FROM_COLUMN,
  FILL_FROM_FORMULA,
  FILL_MISSING,
  DROP_COLUMN,
  DEDUPE,
  DROP_ROWS,
]

const SAFE = {
  C15_formatted_numbers: (issue) => [
    {
      op: REFORMAT_NUMBER,
      column: issue.column,
      label: `read '${issue.column}' as numbers by taking the formatting off`,
    },
  ],

  C16_mixed_date_formats: (issue) => [
    {
      op: REFORMAT_DATE,
      column: issue.column,
      dayfirst: Boolean(issue.evidence?.dayfirst),
      label: `rewrite '${issue.column}' as YYYY-MM-DD`,
    },
  ],

  C17_inconsistent_booleans: (issue) => [
    {
      op: NORMALIZE_BOOLEAN,
      column: issue.column,
      label:
        `write the ${issue.evidence?.distinct ?? ''} spellings in '${issue.column}' ` +
        'consistently as true and false',
    },
  ],

  C18_out_of_band_code: (issue) => [
    {
      op: BLANK_VALUES,
      column: issue.column,
      forms: issue.evidence?.forms ?? [],
      label: `blank the ${issue.total_affected} rows where '${issue.column}' is ${issue.evidence?.code}`,
    },
  ],

  C14_untrimmed: () => [{ op: TRIM, label: 'trim the space around every value' }],

  C20_invisible_characters: (issue) => [
    {
      op: STRIP_INVISIBLE,
      label: `clear the invisible characters out of ${issue.total_affected} cells`,
    },
  ],

  C21_markup: (issue) => [
    {
      op: STRIP_MARKUP,
      column: issue.column,
      label: `take the HTML out of ${issue.total_affected} values in '${issue.column}'`,
    },
  ],

  C11_sentinel_values: (issue) => [
    {
      op: BLANK_VALUES,
      column: issue.column,
      forms: issue.evidence?.forms ?? [],
      label:
        `blank ${issue.evidence?.count ?? 0} cells in '${issue.column}' that say ` +
        `${(issue.evidence?.forms ?? []).slice(0, 2).map((f) => `"${f}"`).join(' or ')}`,
    },
  ],

  C5_categorical_inconsistency: (issue) =>
    Object.entries(issue.evidence?.canonical ?? {}).map(([to, from]) => ({
      op: NORMALIZE,
      column: issue.column,
      from,
      to,
      label: `normalise ${from.length} spellings in '${issue.column}'`,
    })),

  C12_functional_dependency: (issue) => [
    {
      op: FILL_FROM_COLUMN,
      column: issue.column,
      source: issue.evidence?.source,
      mapping: issue.evidence?.mapping ?? {},
      label:
        `recover ${issue.total_affected} missing '${issue.column}' values by looking them ` +
        `up from '${issue.evidence?.source}'`,
    },
  ],

  C13_arithmetic_relation: (issue) => [
    {
      op: FILL_FROM_FORMULA,
      column: issue.column,
      left: issue.evidence?.left,
      right: issue.evidence?.right,
      operation: issue.evidence?.operation,
      label: `compute ${issue.total_affected} missing '${issue.column}' values from ${issue.evidence?.formula}`,
    },
  ],

  C1_missingness: (issue) => [
    {
      op: FILL_MISSING,
      column: issue.column,
      value: issue.evidence?.fill_with ?? 'Unknown',
      label: `label ${issue.total_affected} unrecorded '${issue.column}' values as Unknown`,
    },
  ],

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

  D5_summary_row: (issue) => [
    {
      op: DROP_ROWS,
      rowIndices: issue.row_indices,
      label: 'drop the totals row at the bottom, which is not a record',
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

// Columns the tool is about to ask the user to delete. Editing one silently is
// work the user is likely to throw away, and it muddies the edit log with
// changes to a column that should not have been there in the first place.
function contestedColumns(issues) {
  return new Set(
    issues
      .filter((i) => i.check === 'C10_leakage' || i.check === 'C3_id_like')
      .map((i) => i.column)
      .filter(Boolean),
  )
}

export function safeFixes(issues = []) {
  const contested = contestedColumns(issues)
  const edits = []
  for (const issue of issues) {
    if (issue.column && contested.has(issue.column)) continue
    // Several checks are certain about what they found and uncertain about what
    // should happen to it: a marker that might be a real answer, spellings that
    // might be a real distinction, dates that fit two readings, rows that might
    // be separate events. They say so, and the one-click button listens.
    if (issue.evidence?.auto_apply === false) continue
    const build = SAFE[issue.check]
    if (!build) continue
    // C1 fires on every column with gaps, but only a category can be labelled
    // Unknown. Filling a number that way would invent data.
    if (issue.check === 'C1_missingness' && issue.suggested_action !== 'fill_missing') continue
    for (const edit of build(issue)) {
      if (edit.op === NORMALIZE && !edit.from?.length) continue
      if (edit.op === BLANK_VALUES && !edit.forms?.length) continue
      if (edit.op === DROP_ROWS && !edit.rowIndices?.length) continue
      if (edit.op === FILL_FROM_COLUMN && !edit.source) continue
      if (edit.op === FILL_FROM_FORMULA && !(edit.left && edit.right && edit.operation)) continue
      edits.push(edit)
    }
  }
  return edits.sort((a, b) => ORDER.indexOf(a.op) - ORDER.indexOf(b.op))
}

export function describeFixes(edits) {
  return edits.map((edit) => edit.label).filter(Boolean)
}
