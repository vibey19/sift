import React from 'react'
import { createRoot } from 'react-dom/client'

import App from './App.jsx'
import Landing from './Landing.jsx'
import './theme.css'

// Two routes and no router. React Router would be a dependency and a bundle for
// a decision this file makes in one line.
const isApp = window.location.pathname.startsWith('/app')

// The two surfaces have different page backgrounds, and the body is painted
// behind the app, so the switch has to happen here rather than in a component.
document.body.dataset.surface = isApp ? 'app' : 'landing'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>{isApp ? <App /> : <Landing />}</React.StrictMode>,
)
