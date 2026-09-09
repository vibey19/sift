import React, { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'

import App from './App.jsx'
import Landing from './Landing.jsx'
import './theme.css'

// One page, two surfaces. The auditor used to live at its own route, which meant
// a file picked on the landing page could not survive the navigation. Now the
// landing page hands the file straight over and the view swaps in place.
//
// /app still works as a direct entry point, and history is pushed either way so
// the browser's back button behaves the way people expect it to.
function Root() {
  const [inApp, setInApp] = useState(() => window.location.pathname.startsWith('/app'))
  const [handoff, setHandoff] = useState(null)

  useEffect(() => {
    document.body.dataset.surface = inApp ? 'app' : 'landing'
  }, [inApp])

  useEffect(() => {
    const onPop = () => setInApp(window.location.pathname.startsWith('/app'))
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  const open = (file) => {
    setHandoff(file)
    setInApp(true)
    if (!window.location.pathname.startsWith('/app')) {
      window.history.pushState({}, '', '/app')
    }
    window.scrollTo(0, 0)
  }

  const leave = () => {
    setHandoff(null)
    setInApp(false)
    window.history.pushState({}, '', '/')
    window.scrollTo(0, 0)
  }

  return inApp ? <App handoff={handoff} onLeave={leave} /> : <Landing onOpen={open} />
}

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <Root />
  </React.StrictMode>,
)
