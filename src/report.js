// The Markdown audit report.
//
// Built in the browser rather than on the server, which is a departure from the
// original file layout. The report has to describe the data as it stands now,
// including everything the edit log has done to it, and the edit log only exists
// here. A server-rendered report would describe the file as it was uploaded and
// quietly disagree with the CSV downloaded beside it.

const TAGS = { high: 'HIGH', medium: 'MEDIUM', low: 'LOW' }
const ORDER = ['high', 'medium', 'low']

function table(rows) {
  const widths = rows[0].map((_, i) => Math.max(...rows.map((r) => String(r[i]).length)))
  const line = (cells) => `| ${cells.map((c, i) => String(c).padEnd(widths[i])).join(' | ')} |`
  return [
    line(rows[0]),
    `|${widths.map((w) => '-'.repeat(w + 2)).join('|')}|`,
    ...rows.slice(1).map(line),
  ].join('\n')
}

function rowList(indices, total) {
  if (!indices.length) return ''
  const shown = indices.slice(0, 30).join(', ')
  const more = total > indices.length ? `, and ${total - indices.length} more` : ''
  const cut = indices.length > 30 ? ` (first 30 of ${indices.length} listed)` : ''
  return `\n  Rows: ${shown}${indices.length > 30 ? ' ...' : ''}${more}${cut}\n`
}

export function buildReport({ dataset, result, mapping, edits, current }) {
  const { issues, summary } = result
  const dropped = dataset.rows.length - current.rows.length
  const droppedCols = dataset.columns.length - current.columns.length

  const out = []
  out.push(`# Data quality audit: ${dataset.name}`)
  out.push('')
  out.push(`Run on ${new Date().toISOString().slice(0, 10)} with Sift.`)
  out.push('')

  out.push('## Summary')
  out.push('')
  out.push(
    table([
      ['Measure', 'Value'],
      ['Rows audited', dataset.rows.length.toLocaleString()],
      ['Columns', String(dataset.columns.length)],
      ['Label column', mapping.label ?? 'none chosen'],
      ['Split column', mapping.split ?? 'none chosen'],
      ['High severity', String(summary.high)],
      ['Medium severity', String(summary.medium)],
      ['Low severity', String(summary.low)],
      ['Rows affected', summary.rows_affected.toLocaleString()],
      [
        'Cross-validated accuracy',
        summary.cv_accuracy == null ? 'not measured' : summary.cv_accuracy.toFixed(3),
      ],
    ]),
  )
  out.push('')

  if (summary.cv_accuracy != null) {
    out.push(
      summary.cv_accuracy < 0.6
        ? `> The model behind the mislabel flags scored ${summary.cv_accuracy.toFixed(2)} in ` +
            '> cross-validation. It cannot model this task, so those flags are close to noise. ' +
            'Treat them as low confidence.'
        : `The mislabel flags below come from a model scoring ${summary.cv_accuracy.toFixed(3)} ` +
            'in cross-validation, so it is worth listening to. Every row was scored by a model ' +
            'that never saw it during training.',
    )
    out.push('')
  }

  if (summary.skipped_checks?.length) {
    out.push('### Checks that did not run')
    out.push('')
    for (const skipped of summary.skipped_checks) {
      out.push(`- \`${skipped.check}\` — ${skipped.reason}`)
    }
    out.push('')
  }

  out.push('## Findings')
  out.push('')
  if (!issues.length) out.push('Nothing was flagged.')

  for (const severity of ORDER) {
    const group = issues.filter((i) => i.severity === severity)
    if (!group.length) continue
    out.push(`### ${TAGS[severity]}`)
    out.push('')
    for (const issue of group) {
      out.push(`**${issue.title}**`)
      out.push('')
      out.push(`${issue.detail}`)
      out.push('')
      out.push(`- Check: \`${issue.check}\``)
      if (issue.column) out.push(`- Column: \`${issue.column}\``)
      out.push(`- Affected: ${issue.total_affected.toLocaleString()}`)
      out.push(`- Suggested action: \`${issue.suggested_action}\``)
      const rows = rowList(issue.row_indices, issue.total_affected)
      if (rows) out.push(rows.trimEnd())
      out.push('')
    }
  }

  out.push('## Changes made')
  out.push('')
  if (!edits.length) {
    out.push('None. This report describes the file as it was uploaded.')
  } else {
    edits.forEach((edit, i) => out.push(`${i + 1}. ${describeEdit(edit)}`))
    out.push('')
    out.push(
      `The exported file has ${current.rows.length.toLocaleString()} rows and ` +
        `${current.columns.length} columns, down from ${dataset.rows.length.toLocaleString()} ` +
        `and ${dataset.columns.length}: ${dropped.toLocaleString()} rows and ${droppedCols} ` +
        'columns removed.',
    )
  }
  out.push('')
  out.push('---')
  out.push('')
  out.push(
    'Thresholds and check definitions are in `api/sift/config.py`. Nothing from this ' +
      'dataset was stored: the audit ran in a stateless function and the file stayed in ' +
      'the browser.',
  )
  out.push('')

  return out.join('\n')
}

function describeEdit(edit) {
  const n = edit.rowIndices?.length ?? Object.keys(edit.values ?? {}).length
  switch (edit.op) {
    case 'drop_rows':
      return `Dropped ${n} rows.`
    case 'dedupe':
      return 'Removed duplicate rows, keeping the first of each group.'
    case 'relabel':
      return `Relabelled ${n} rows in \`${edit.column}\` to the model's prediction.`
    case 'normalize_values':
      return `Normalised ${edit.from.length} spellings in \`${edit.column}\` to \`${edit.to}\`.`
    case 'drop_column':
      return `Dropped the \`${edit.column}\` column.`
    default:
      return edit.op
  }
}
