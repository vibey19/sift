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
    // A real export, so it carries no label or split column and the label-aware
    // checks report themselves as skipped. That is the honest result for a file
    // of this shape, and worth showing.
    name: 'cafe_dirty.csv',
    path: '/samples/cafe_dirty.csv',
    wrong:
      'Seven columns writing missing values as ERROR and UNKNOWN, and 1,398 ' +
      'blank cells the remaining columns can work back out.',
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
