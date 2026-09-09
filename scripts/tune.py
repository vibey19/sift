"""Sweep the five hand-set thresholds against the recorded defects.

Prints, for each candidate value, what it catches and what it costs. The numbers
that come out of here are what belongs in the README: the value chosen, and what
happened at the values rejected.

    python scripts/tune.py
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")

from sklearn.ensemble import HistGradientBoostingClassifier  # noqa: E402
from sklearn.model_selection import StratifiedKFold, cross_val_predict, cross_val_score  # noqa: E402
from sklearn.tree import DecisionTreeClassifier  # noqa: E402

from scripts.make_dirty import make_churn, make_reviews  # noqa: E402
from sift import config, encode, profile as prof, runner  # noqa: E402
from sift.checks import dataset as dataset_checks  # noqa: E402


def _load(builder):
    df, truth = builder()
    import io

    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return runner.load(buf.getvalue()), truth


def _table(title: str, header: list[str], body: list[list]) -> None:
    print(f"\n{title}")
    widths = [max(len(str(h)), *(len(str(r[i])) for r in body)) for i, h in enumerate(header)]
    print("  " + "  ".join(str(h).ljust(w) for h, w in zip(header, widths)))
    print("  " + "  ".join("-" * w for w in widths))
    for row in body:
        print("  " + "  ".join(str(c).ljust(w) for c, w in zip(row, widths)))


def _scores(df, label):
    profiles = prof.profile_frame(df)
    encoded = encode.build(df, profiles, label, "split")
    labels = df[label].where(~prof.missing_mask(df[label]))
    counts = labels.value_counts()
    keep = labels.notna() & ~labels.isin(counts[counts < config.MIN_CLASS_MEMBERS_FOR_CV].index)
    pos = np.flatnonzero(keep.to_numpy())
    y = labels.to_numpy()[pos].astype(str)
    proba = cross_val_predict(
        HistGradientBoostingClassifier(random_state=0), encoded.X[pos], y,
        cv=StratifiedKFold(config.CV_FOLDS, shuffle=True, random_state=0),
        method="predict_proba",
    )
    classes = np.unique(y)
    idx = {c: i for i, c in enumerate(classes)}
    p_given = proba[np.arange(len(y)), [idx[v] for v in y]]
    return df.index.to_numpy()[pos], p_given, proba.max(axis=1), float((classes[proba.argmax(1)] == y).mean())


def mislabel_sweep(df, truth, label, name):
    rows, p_given, p_top, acc = _scores(df, label)
    planted = set(truth["mislabelled_idx"])
    body = []
    for given_max in (0.05, 0.10, 0.20, 0.30):
        for top_min in (0.50, 0.75, 0.90):
            flagged = set(rows[(p_given < given_max) & (p_top > top_min)])
            hit = len(flagged & planted)
            body.append([
                given_max, top_min, len(flagged), f"{hit}/{len(planted)}",
                f"{hit / max(len(flagged), 1):.2f}",
            ])
    _table(
        f"R1 mislabels - {name} (cross-validated accuracy {acc:.3f})",
        ["P_GIVEN_MAX", "P_TOP_MIN", "flagged", "of planted", "precision"], body,
    )


def leakage_sweep(df, truth, label, name):
    profiles = prof.profile_frame(df)
    labels = df[label].where(~prof.missing_mask(df[label]))
    counts = labels.value_counts()
    keep = labels.notna() & ~labels.isin(counts[counts < config.MIN_CLASS_MEMBERS_FOR_CV].index)
    y = labels[keep].astype(str).to_numpy()
    majority = float(pd.Series(y).value_counts(normalize=True).iloc[0])
    folds = StratifiedKFold(config.CV_FOLDS, shuffle=True, random_state=0)

    from sift.checks.columns import _encode_single

    body = []
    for p in profiles:
        col = p["name"]
        if col in {label, "split"} or p["inferred_type"] == prof.CONSTANT:
            continue
        x = _encode_single(df[keep], col, p["inferred_type"])
        if x is None:
            continue
        score = float(cross_val_score(
            DecisionTreeClassifier(max_depth=3, random_state=0), x, y, cv=folds).mean())
        body.append([col, f"{score:.4f}", "planted leak" if col in truth.get("leaked_cols", []) else ""])
    body.sort(key=lambda r: -float(r[1]))
    _table(
        f"C10 leakage - {name} (majority baseline {majority:.3f})",
        ["column", "accuracy alone", ""], body,
    )


def near_dup_sweep(df, truth, name):
    profiles = prof.profile_frame(df)
    planted = set(truth["near_dup_idx"])
    stock = set(truth.get("stock_phrase_idx", []))
    body = []
    original = config.NEAR_DUP_THRESHOLD
    for th in (0.60, 0.70, 0.75, 0.80, 0.90, 0.97, 0.99):
        config.NEAR_DUP_THRESHOLD = th
        pairs = dataset_checks._candidate_pairs(df, profiles, list(df.columns))
        rows = {r for pair in pairs for r in pair}
        body.append([
            th, len(pairs), f"{len(rows & planted)}/{len(planted)}",
            len(rows - planted - stock), len(rows & stock),
        ])
    config.NEAR_DUP_THRESHOLD = original
    _table(
        f"D2 near duplicates - {name}",
        ["THRESHOLD", "pairs", "planted rows found", "other rows", "stock-phrase rows"], body,
    )


def main() -> None:
    churn, churn_truth = _load(make_churn)
    reviews, reviews_truth = _load(make_reviews)

    leakage_sweep(churn, churn_truth, "churned", "churn")
    leakage_sweep(reviews, reviews_truth, "sentiment", "reviews")
    mislabel_sweep(churn, churn_truth, "churned", "churn")
    mislabel_sweep(reviews, reviews_truth, "sentiment", "reviews")
    near_dup_sweep(churn, churn_truth, "churn")
    near_dup_sweep(reviews, reviews_truth, "reviews")

    print("\nWEAK_MODEL_ACCURACY is a judgement call, not a sweep: it is the accuracy")
    print("below which you would not trust the flags at all. Compare the two")
    print("cross-validated accuracies above and pick where your own trust runs out.")


if __name__ == "__main__":
    main()
