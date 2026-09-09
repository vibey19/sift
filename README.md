# Sift

Sift takes a CSV and tells you which rows and columns are probably wrong before you train anything on them.

Live: `<url>` · Sample datasets are loaded from the empty state, so you can try it without uploading anything.

## Why I built it

I kept reading about models that scored well in validation and fell apart in production, and in most of the write-ups the cause turned out to be the data rather than the model. A column that quietly contained the answer. A few hundred rows labelled wrong. The same records sitting in both the training and test split.

None of that is hard to find once you know to look for it. It is just tedious, so nobody looks. I wanted a tool that does the looking, and I wanted to build the detection logic myself rather than call an API and hope.

## What it checks

Fifteen checks, grouped by what they look at.

**The whole dataset** — exact duplicate rows, near-duplicate rows, class imbalance, and rows that appear on both sides of a train/test split.

**Individual columns** — missing values, constant and near-constant columns, ID-like columns sitting in the feature set, mixed types in one column, categorical values that differ only by case or whitespace, rare categories, numeric outliers, implausible values, redundant column pairs, and single-column label leakage.

**Individual rows** — labels the model disagrees with.

Each finding comes back with a severity, a sentence explaining what it means, and the row numbers it applies to.

## How the interesting three work

Most of the checks are rules. These three are not, and they are the reason the project exists.

### Mislabelled rows

Training a model on a dataset and then asking it which rows look wrong does not work, because the model has already memorised those rows. So Sift uses 5-fold cross-validated predictions instead. Every row gets scored by a model that never saw it during training.

For each row I take the probability the model assigned to the label the row actually has, and the highest probability it assigned to anything. When the first number is low and the second is high, the model is confident and it disagrees with you. The gap between them is the ranking score.

Two guardrails matter here. Classes with fewer than five members get dropped before cross-validation, because stratified 5-fold cannot split them and the failure is silent. And the overall cross-validation accuracy comes back with the results — if the model only scored 0.55, it cannot model your task, and every flag it produced is noise. Sift prints that number next to the flags rather than hiding it.

### Leaked features

Sift fits a depth-3 decision tree on each column on its own and cross-validates it. If any single column predicts your target at 98% accuracy, that column is not a strong feature. It is the answer copied into the input, usually because it was populated after the outcome was known.

This is the check that has caught the most interesting things for me during testing, and it is the cheapest one in the whole tool.

### Train/test contamination

If a split column exists, Sift looks for rows that appear on both sides, exactly and approximately. Exact matches are a pandas one-liner. Near matches use the same row encoding as duplicate detection: text through TF-IDF and SVD, numbers rank-scaled, categories one-hot encoded, then cosine similarity computed in chunks.

Contamination is the failure that produces the most confident wrong result, because the validation score comes back high and there is nothing in the training curve to suggest anything went wrong.

## The thresholds I chose and why

<!--
TODO: after tuning, two sentences per constant - the value and what the
rejected values did.

NEAR_DUP_THRESHOLD -
MISLABEL_P_GIVEN_MAX / MISLABEL_P_TOP_MIN -
LEAKAGE_ACCURACY -
WEAK_MODEL_ACCURACY -
-->

## What it can't do

- Files up to 4.5MB, which works out to roughly 30,000–50,000 rows depending on width. That is a Vercel serverless request body limit. The fix is client-side upload straight to blob storage, which I have not built yet.
- Near-duplicate detection is capped at 20,000 rows. Exact cosine similarity is quadratic, and past that point it needs approximate nearest neighbours — FAISS or an LSH scheme. At the sizes Sift handles today, exact is faster than building the index would be.
- Classification labels only. Regression targets need a different mislabel formulation and I have not written it.
- CSV and TSV only.
- Nothing is saved. Reload the page and your work is gone. That is deliberate, not an oversight — the backend stores nothing at all.

## Running it locally

```
git clone <repo>
cd sift
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
npm install
vercel dev
```

`vercel dev` runs the Python function and the Vite dev server together, which avoids CORS setup. Tests are `pytest -q`.

## Stack

FastAPI for the single audit endpoint. pandas and scikit-learn for everything analytical — no deep learning, no API calls, no model downloads.

Text features go through TF-IDF and TruncatedSVD rather than sentence embeddings. Embeddings would be slightly better at catching paraphrased duplicates, but sentence-transformers pulls in PyTorch, which is roughly 800MB and would not deploy on a free tier. TF-IDF installs in seconds and the quality difference on this task is small.

React with plain JSX on the frontend, deployed on Vercel. The browser holds the dataset for the whole session and every edit happens client-side, so the server is stateless by construction rather than by discipline.
