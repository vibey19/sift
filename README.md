# Sift

Sift cleans a messy CSV without the notebook. Drop a file in and it runs twenty-nine checks, fixes the unambiguous problems in one click, and hands you the rest with the row numbers and a reason.

Live: <https://sift-csv.vercel.app/> · Sample datasets load from the empty state, so you can try it without uploading anything.

![Dropping in a sample CSV, applying the seven safe fixes in one click, then dropping the leaked column it found and watching the reported accuracy fall from 0.986 to 0.706](docs/demo.gif)

## Why

Every new dataset meant the same half hour. Read it in, check the dtypes, count the nulls, find the duplicates, discover the category column has four spellings of the same value, write the same six lines I wrote last month, lose the notebook, write them again for the next file.

None of it is difficult. It is repetitive enough that people skip it, and the faults worth catching hide behind the boring ones: a column that quietly contains the answer, a few hundred rows labelled wrong, the same records sitting in both the training and test split.

The split the tool draws is between fixes that need a decision and fixes that do not. Duplicates, spelling variants, columns that never vary and rows that are more than half empty get applied together on one button, because there is no judgement in any of them. Everything else — the leaked column, the contaminated rows and the model's opinion about your labels — is shown with its evidence and left alone until you say so.

## What it checks

Twenty-nine checks. Twenty-six run without a label column; the other three say so rather than quietly returning less.

- **Dataset** — exact and near-duplicate rows, class imbalance, rows on both sides of a train/test split, a totals row pretending to be a record.
- **Columns** — missing values, constant and near-constant columns, ID-like columns in the feature set, mixed types, categories differing only by case or whitespace, rare categories, outliers, implausible values, redundant pairs, single-column label leakage.
- **Formatting** — words standing in for a missing value, numbers wearing a currency symbol or unit, one column in three date formats, true and false spelled six ways, `-999` meaning "no reading", one company named four ways, zero-width characters, HTML left on scraped text.
- **Relationships** — a column determined by another, a column that is the sum or product of two others, rows breaking an order the file otherwise keeps. The first two can fill a gap by deduction rather than by guessing.
- **Rows** — labels the model disagrees with.

Each finding comes back with a severity, a sentence explaining what it means and why it matters, and the row numbers it applies to.

## How the interesting three work

Most of the checks are rules. These three are not, and they are the reason the project exists.

**Mislabelled rows.** Training a model and then asking it which rows look wrong does not work, because it has already memorised them. Sift uses 5-fold cross-validated predictions, so every row is scored by a model that never saw it. A row is flagged when the probability given to its stated label is low and the probability given to something else is high. Two guardrails: classes with fewer than five members get dropped before cross-validation, because stratified 5-fold cannot split them and the failure is silent; and the overall accuracy comes back with the results, because if the model only scored 0.55 every flag it produced is noise.

**Leaked features.** A depth-3 decision tree is fitted on each column on its own and cross-validated. If one column predicts the target far better than guessing the biggest class, it is not a strong feature — it is the answer copied into the input, usually populated after the outcome was known. The comparison is against the majority-class baseline rather than a flat number; without that, a label that is 99% one value makes every column look like a leak. Cheapest check in the tool, and it has caught the most interesting things.

**Train/test contamination.** Rows appearing on both sides of a split column, exactly and approximately. This is the failure that produces the most confident wrong result, because the validation score comes back high and nothing in the training curve suggests anything went wrong.

## Watching it argue against itself

Audit the churn sample and it reports 0.985 cross-validation accuracy and flags 39 mislabelled rows. Drop the leaked column it just told you about, drop the contaminated rows, and re-audit:

```
before  ·  cv accuracy 0.985  ·  39 rows flagged
after   ·  cv accuracy 0.710  ·  108 rows flagged
```

Accuracy falls and the flag count nearly triples, because without the leak the model is genuinely uncertain and disagrees with far more rows. The first line is the one you would have believed if the tool had hidden its own accuracy. That is the whole argument for printing it next to the flags.

The five numbers that decide what gets flagged were set by sweeping each one against datasets with faults injected on purpose, so recall and false positives could be measured rather than guessed: [the thresholds I chose and why](docs/thresholds.md).

## What it can't do

- Files up to 50,000 rows. The browser gzips the upload and CSV compresses about five to one, so a file that size arrives in well under a megabyte. The row limit is the real one, and it is there because the audit holds the whole frame in memory.
- Classification labels only. Regression targets need a different mislabel formulation and I have not written it.
- CSV and TSV only.
- Nothing is saved. Reload the page and your work is gone. That is deliberate, not an oversight. The backend stores nothing at all.

## Running it locally

```
git clone https://github.com/vibey19/sift
cd sift
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
npm install
```

Then two terminals:

```
uvicorn api.index:app --reload --port 8000
npm run dev
```

The Vite dev server proxies `/api` to the Python process, so the frontend calls the same paths it will in production. Tests are `pytest -q` for the backend and `npm test` for the browser code. `python scripts/make_dirty.py` regenerates the sample datasets, and `python scripts/tune.py` reproduces the threshold tables.

Pin the virtualenv to Python 3.12. Building locally on a newer version means wheels resolve differently in development and deployment.

## Stack

Two endpoints. `POST /api/profile` returns column types so the label picker can render, and `POST /api/audit` returns every finding. The file crosses the wire twice, once per call, which is the cost of letting you choose a label column before the label-aware checks run.

pandas and scikit-learn do everything analytical. No deep learning, no API calls, no model downloads. Text features go through TF-IDF and TruncatedSVD rather than sentence embeddings — embeddings would be slightly better at catching paraphrased duplicates, but sentence-transformers pulls in PyTorch, which is roughly 800MB and would not deploy on a free tier.

The frontend is React with plain JSX and nothing beyond it: no router, no state library, no component library, no CSS framework. The CSV parser is written out by hand in `src/csv.js`, because the browser owns the file for the whole session and something had to parse it. Edits are kept as an append-only log and replayed over the original rows on every render, which makes undo a single pop and keeps the parsed file authoritative. The browser holds the dataset for the whole session and every edit happens client-side, so the server is stateless by construction rather than by discipline.
