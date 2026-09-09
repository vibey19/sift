import { useEffect, useState } from 'react'

import { ApiError, audit } from './api.js'

// Phase 4 shell: proves the client layer and the fixtures load. The real screen
// arrives in phase 5.
export default function App() {
  const [state, setState] = useState({ status: 'loading' })

  useEffect(() => {
    const csv = 'a,b\n1,2\n1,2\n'
    audit(csv, { fixture: 'audit_churn' })
      .then((data) => setState({ status: 'ready', data }))
      .catch((error) =>
        setState({ status: 'error', message: error instanceof ApiError ? error.message : String(error) }),
      )
  }, [])

  if (state.status === 'loading') return <main style={S.page}>auditing...</main>
  if (state.status === 'error') return <main style={S.page}>{state.message}</main>

  const { issues, summary } = state.data
  return (
    <main style={S.page}>
      <h1>Sift</h1>
      <p>
        {summary.high} high, {summary.medium} medium, {summary.low} low across{' '}
        {summary.rows_affected} rows.
        {summary.cv_accuracy != null && ` Cross-validated accuracy ${summary.cv_accuracy.toFixed(3)}.`}
      </p>
      <ul>
        {issues.map((issue) => (
          <li key={issue.id}>
            [{issue.severity.toUpperCase()}] {issue.title}
          </li>
        ))}
      </ul>
    </main>
  )
}

const S = { page: { fontFamily: 'monospace', padding: 24, maxWidth: 900 } }
