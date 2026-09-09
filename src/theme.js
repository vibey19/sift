// Theme lives on the document element so the first paint is already correct.
// A theme applied from a React effect flashes the wrong colours first.

const KEY = 'sift-theme'

export function readTheme() {
  try {
    const saved = localStorage.getItem(KEY)
    if (saved === 'light' || saved === 'dark') return saved
  } catch {
    // Private browsing throws on access. Fall through to the system setting.
  }
  return window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
}

export function applyTheme(theme) {
  document.documentElement.dataset.theme = theme
  try {
    localStorage.setItem(KEY, theme)
  } catch {
    // Not being able to remember the choice is not a reason to refuse it.
  }
}
