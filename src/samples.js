import { decodeBytes } from './decode.js'

// The two sample datasets, described by what is actually wrong with them. Shared
// by the landing page's drop card and the auditor's empty state so the two can
// never drift apart.

export const SAMPLES = [
  {
    name: 'churn_dirty.csv',
    path: '/samples/churn_dirty.csv',
    label: 'churned',
    split: 'split',
    wrong:
      'A column populated only after customers left, 25 records sitting in both ' +
      'train and test, and 40 labels flipped.',
  },
  {
    name: 'reviews_dirty.csv',
    path: '/samples/reviews_dirty.csv',
    label: 'sentiment',
    split: 'split',
    wrong:
      'Three sentiment classes written nine different ways, plus re-posted ' +
      'reviews with one figure changed.',
  },
]

export const ACCEPTS = /\.(csv|tsv|txt)$/i

export async function readSample(sample) {
  const response = await fetch(sample.path)
  if (!response.ok) throw new Error(`Could not load ${sample.name}`)
  // Through the same decoder as an upload, so a sample and a file the user
  // brings take exactly the same path into the parser.
  const { text, encoding } = decodeBytes(await response.arrayBuffer())
  return {
    name: sample.name,
    text,
    hints: { label: sample.label, split: sample.split, encoding },
  }
}
