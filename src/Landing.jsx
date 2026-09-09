import { useEffect } from 'react'

import Demo from './components/Demo.jsx'
import DropCard from './components/DropCard.jsx'
import ThemeToggle from './components/ThemeToggle.jsx'
import { useReveal } from './useReveal.js'

const GITHUB = 'https://github.com/vibey19/sift'

const CATCHES = [
  {
    tag: 'Fixed in one click',
    title: 'The tedious half',
    body:
      'Exact duplicates, four spellings of the same category, columns that never ' +
      'vary, rows that are more than half empty, money that will not parse as a ' +
      'number, three date formats in one column, and gaps that another column ' +
      'already answers. None of it needs a decision from you, so Sift offers to ' +
      'fix all of it at once and shows you exactly what it did.',
  },
  {
    tag: 'Your call',
    title: 'Leaked columns',
    body:
      'A column that predicts your target on its own is not a strong feature. It is ' +
      'the answer, copied into the input, usually written after the outcome was ' +
      'known. Sift tests every column separately and tells you which are too good ' +
      'to be true. Dropping one is your decision, not its.',
  },
  {
    tag: 'Your call',
    title: 'Train/test contamination',
    body:
      'Rows sitting on both sides of your split, exactly or nearly. This is the one ' +
      'that turns a 0.97 validation score into a 0.61 in production, with nothing in ' +
      'the training curve to warn you.',
  },
  {
    tag: 'Your call',
    title: 'Mislabelled rows',
    body:
      'Every row is scored by a model that never saw it during training. Where that ' +
      'model is confident and disagrees with the label on file, you get a flag, ' +
      'ranked by how badly the two disagree.',
  },
]

const STEPS = [
  ['01', 'Drop in a CSV', 'It parses in your browser and is audited straight away. No sign-up, no configuration, no waiting for a job.'],
  ['02', 'Apply the safe fixes', 'One button for everything unambiguous. Every edit is listed and every one can be undone.'],
  ['03', 'Decide the rest, export', 'Work through what needs judgement, then download the cleaned CSV and a Markdown report of what was wrong.'],
]

const LIMITS = [
  'Files up to 50,000 rows. The upload is compressed on the way out, so a file that size arrives in well under a megabyte.',
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
          <p className="eyebrow">CSV cleaning, without the notebook</p>
          <h1>Stop rewriting the same cleaning script for every dataset.</h1>
          <p className="lede">
            Drop in a CSV. Sift runs twenty-nine checks, tells you what is wrong in plain English,
            and fixes the safe ones in one click. The rest it hands to you with the row numbers
            and a reason. Nothing is stored: your file is audited by a stateless function and
            forgotten the moment the response is sent.
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
          <span>29 checks</span>
          <span>one-click fixes</span>
          <span>no sign-up</span>
          <span>nothing stored</span>
        </div>
      </div>

      <section className="section">
        <div className="wrap prose" data-reveal>
          <p className="eyebrow">The problem</p>
          <h2>You already know how to clean data.</h2>
          <p>
            That is the annoying part. Every new dataset means the same half hour: read it in,
            check the dtypes, count the nulls, find the duplicates, discover that the category
            column has four spellings of the same value, write the same six lines you wrote
            last month, lose the notebook, write them again for the next file.
          </p>
          <p>
            None of it is difficult. It is just repetitive enough that people skip it, and the
            things worth catching hide behind the boring things. Sift does the repetitive part
            in one click, then spends the rest of its time on the faults a quick pass would
            never surface: a column that leaks your target, records sitting in both train and
            test, rows labelled by someone having a bad day.
          </p>
        </div>
      </section>

      <Demo />

      <section className="section" id="catches">
        <div className="wrap" data-reveal>
          <p className="eyebrow">What it catches</p>
          <h2>Twenty-nine checks. It fixes some and asks about the rest.</h2>
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
          <h2 style={{ fontSize: 38, marginBottom: 26 }}>Clean the next one in ten seconds.</h2>
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
