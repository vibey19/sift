import { useEffect } from 'react'

import Demo from './components/Demo.jsx'
import DropCard from './components/DropCard.jsx'
import ThemeToggle from './components/ThemeToggle.jsx'
import { useReveal } from './useReveal.js'

const GITHUB = 'https://github.com/vibey19/sift'

const CATCHES = [
  {
    tag: 'Row level',
    title: 'Mislabelled rows',
    body:
      'Every row is scored by a model that never saw it during training, using 5-fold ' +
      'cross-validated predictions. Where the model is confident and disagrees with the ' +
      'label on file, you get a flag, ranked by how badly the two disagree.',
  },
  {
    tag: 'Column level',
    title: 'Leaked features',
    body:
      'A single column that predicts your target at 98% accuracy is not a strong feature. ' +
      'It is the answer, copied into the input. Sift tests every column on its own and ' +
      'tells you which ones are too good to be true.',
  },
  {
    tag: 'Dataset level',
    title: 'Train/test contamination',
    body:
      'Rows that appear on both sides of your split, exactly or nearly. This is the one ' +
      'that turns a 0.97 validation score into a 0.61 in production, with nothing in the ' +
      'training curve to warn you.',
  },
  {
    tag: 'Everywhere else',
    title: 'Duplicates and dirty categories',
    body:
      'Near-duplicate rows, Positive filed separately from positive, columns that are 99% ' +
      'a single value, and outliers measured by median absolute deviation rather than ' +
      'standard deviation, so extreme values cannot hide inside their own threshold.',
  },
]

const STEPS = [
  ['01', 'Upload a CSV', 'Or load a sample. The file is parsed in your browser and never leaves it except to be audited.'],
  ['02', 'Pick your label column', 'That switches on the mislabel, leakage and contamination checks. Twelve of the fifteen run without one.'],
  ['03', 'Review and export', 'Drop rows, drop columns, normalise spellings, then download the cleaned file.'],
]

const LIMITS = [
  'Files up to 4.5MB, roughly 30–50k rows. That is a serverless request body limit.',
  'Near-duplicate detection is capped at 20,000 rows.',
  'Classification labels only. Regression targets need a different mislabel formulation.',
  'CSV and TSV only.',
  'Nothing is saved. Reload the page and your work is gone.',
]

export default function Landing({ onOpen }) {
  // On a cold load the browser tries to reach the anchor before React has
  // rendered it, so the jump has to happen again once the page exists.
  useReveal()

  useEffect(() => {
    const { hash } = window.location
    if (!hash) return
    document.querySelector(hash)?.scrollIntoView()
  }, [])

  // Still a real link, so it opens in a new tab and shows a URL on hover. The
  // handler only intercepts a plain left click.
  const openBlank = (event) => {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return
    event.preventDefault()
    onOpen(null)
  }

  return (
    <div className="landing">
      <nav className="nav">
        <div className="nav-inner">
          <a className="mark" href="/">SIFT</a>
          <div className="nav-right">
            <a className="plain" href="#demo">Demo</a>
            <a className="plain" href="#catches">Checks</a>
            <a className="plain" href={GITHUB}>GitHub</a>
            <ThemeToggle />
            <a className="btn btn-primary" href="/app" onClick={openBlank}>Open the auditor</a>
          </div>
        </div>
      </nav>

      <header className="wrap hero">
        <div>
          <p className="eyebrow">Dataset quality auditor</p>
          <h1>Find the rows that are quietly ruining your model.</h1>
          <p className="lede">
            Sift audits any CSV for mislabelled rows, leaked features, train/test contamination
            and near-duplicates. Nothing is stored — your file is audited by a stateless
            function and forgotten the moment the response is sent.
          </p>
          <div className="btn-row" style={{ marginTop: 28 }}>
            <a className="btn" href="#demo">See a sample run</a>
            <a className="btn" href={GITHUB}>Read the code</a>
          </div>
        </div>

        <DropCard onOpen={onOpen} />
      </header>

      <div className="strip">
        <div className="strip-inner">
          <span>15 checks</span>
          <span>no API keys</span>
          <span>no model downloads</span>
          <span>nothing stored</span>
        </div>
      </div>

      <section className="section">
        <div className="wrap prose" data-reveal>
          <p className="eyebrow">The problem</p>
          <h2>Usually the model is fine.</h2>
          <p>
            Most model debugging starts with the model. A column that leaks the answer, a few
            hundred rows labelled by someone having a bad day, the same records sitting in both
            train and test — these produce validation numbers that look excellent and collapse
            the moment the thing meets real data.
          </p>
          <p>
            None of it is hard to find once you know to look. It is just tedious, which is why
            most people never look. Sift does the looking, and it does it with scikit-learn and
            pandas rather than an API call and a hope.
          </p>
        </div>
      </section>

      <Demo />

      <section className="section" id="catches">
        <div className="wrap" data-reveal>
          <p className="eyebrow">What it catches</p>
          <h2>Fifteen checks, four of which matter most.</h2>
          <div className="grid-2" style={{ marginTop: 34 }}>
            {CATCHES.map((item) => (
              <article className="card" key={item.title}>
                <p className="label" style={{ marginBottom: 8 }}>{item.tag}</p>
                <h3>{item.title}</h3>
                <p style={{ margin: 0, fontSize: 15 }}>{item.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="section-tight">
        <div className="wrap" data-reveal>
          <p className="eyebrow">How it works</p>
          <div className="grid-3" style={{ marginTop: 24 }}>
            {STEPS.map(([n, title, body]) => (
              <div key={n}>
                <span className="step-n">{n}</span>
                <h3>{title}</h3>
                <p style={{ fontSize: 15, margin: 0 }}>{body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="section">
        <div className="wrap" data-reveal>
          <div className="card" style={{ padding: 40 }}>
            <p className="label" style={{ marginBottom: 10 }}>Why you can trust the flags</p>
            <h2>It tells you when to ignore it.</h2>
            <p style={{ maxWidth: '62ch' }}>
              Every mislabel flag arrives with the cross-validation accuracy of the model that
              produced it. When that number is 0.55, the flags are noise, and Sift says so on
              the flag itself rather than hiding it. A list of suspicious rows means nothing
              until you know whether the model could learn the task at all.
            </p>
            <p style={{ margin: '0 0 18px', maxWidth: '62ch' }}>
              On the sample dataset that plays out in one click. Drop the leaked column and
              re-audit, and the tool reports its own accuracy falling:
            </p>
            <div className="mono" style={{ fontSize: 15, lineHeight: 2 }}>
              <div>before &nbsp;·&nbsp; cv accuracy 0.985 &nbsp;·&nbsp; 39 rows flagged</div>
              <div>after &nbsp;&nbsp;·&nbsp; cv accuracy 0.710 &nbsp;·&nbsp; 108 rows flagged</div>
            </div>
            <p style={{ margin: '18px 0 0', maxWidth: '62ch', fontSize: 15 }}>
              The count goes up because the honest model is less certain. A tool that hid the
              accuracy would have shown you the first line and let you believe it.
            </p>
          </div>
        </div>
      </section>

      <section className="section-tight">
        <div className="wrap prose" data-reveal>
          <p className="eyebrow">Limits</p>
          <h2>What it can't do.</h2>
          <div className="limits">
            <ul>
              {LIMITS.map((limit) => (
                <li key={limit}>{limit}</li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      <section className="section">
        <div className="wrap" style={{ textAlign: 'center' }}>
          <h2 style={{ fontSize: 38, marginBottom: 26 }}>Audit a dataset before you train on it.</h2>
          <a
            className="btn btn-primary"
            href="/app"
            onClick={openBlank}
            style={{ fontSize: 15, padding: '16px 30px' }}
          >
            Open the auditor
          </a>
        </div>
      </section>

      <footer className="foot">
        <div className="foot-inner">
          <span>Built by Jainil Dadhaniya · MSc Data Science, Tampere University</span>
          <a href={GITHUB} style={{ marginLeft: 'auto' }}>GitHub</a>
        </div>
      </footer>
    </div>
  )
}
