import { useEffect } from 'react'

// Reveals anything marked [data-reveal] once it comes into view, then stops
// watching it. Observed rather than tied to a scroll handler, so it costs
// nothing while the page sits still.
export function useReveal(deps = []) {
  useEffect(() => {
    const targets = document.querySelectorAll('[data-reveal]:not([data-reveal="in"])')
    if (!targets.length) return undefined

    if (!('IntersectionObserver' in window)) {
      targets.forEach((el) => el.setAttribute('data-reveal', 'in'))
      return undefined
    }

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue
          entry.target.setAttribute('data-reveal', 'in')
          observer.unobserve(entry.target)
        }
      },
      // Fires a little before the element arrives, so the motion has finished
      // by the time it is properly in view.
      { rootMargin: '0px 0px -12% 0px', threshold: 0.05 },
    )
    targets.forEach((el) => observer.observe(el))
    return () => observer.disconnect()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
}
