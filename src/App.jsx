import { useEffect, useState } from 'react'

// Phase 0 shell. This exists to prove the frontend build deploys and can reach
// the Python function through the /api rewrite. Replaced in phase 5.
export default function App() {
  const [health, setHealth] = useState(null)

  useEffect(() => {
    fetch('/api/health')
      .then((r) => r.json())
      .then(setHealth)
      .catch(() => setHealth({ ok: false }))
  }, [])

  return (
    <main style={{ fontFamily: 'monospace', padding: 24 }}>
      <h1>Sift</h1>
      <p>Dataset quality auditor.</p>
      <pre>{health ? JSON.stringify(health, null, 2) : 'checking api...'}</pre>
    </main>
  )
}
