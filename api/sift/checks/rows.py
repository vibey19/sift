"""R1, probable mislabels.

Asking a model which of its own training rows look wrong does not work, because
it has already memorised them. Every row here is scored by a model that never
saw it, using out-of-fold predictions.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.model_selection import StratifiedKFold, cross_val_predict

from .. import config, profile as prof
from ..encode import Encoded
from ..issue import HIGH, MEDIUM, make_issue

CHECK = "R1_mislabels"


def _skip(reason: str) -> dict:
    return {"issues": [], "cv_accuracy": None, "skipped": [{"check": CHECK, "reason": reason}]}


def run(
    df: pd.DataFrame,
    encoded: Encoded,
    label_column: str | None,
) -> dict:
    if not label_column or label_column not in df.columns:
        return _skip("no label column was chosen")
    if not encoded.usable:
        return _skip("no usable feature columns once ids and constants were dropped")
    if len(df) < config.MISLABEL_MIN_ROWS:
        return _skip(f"fewer than {config.MISLABEL_MIN_ROWS} rows")

    labels = df[label_column].where(~prof.missing_mask(df[label_column]))
    # The model is given the label with its spelling settled first. A column
    # holding "positive", "Positive" and " positive" has three classes as far
    # as the fold splitter is concerned, and the model is asked to tell them
    # apart using features that cannot possibly say which spelling a row used.
    # It spends its whole budget failing at that, and then reports every row
    # whose spelling it guessed wrong as a probable mislabel. On the reviews
    # sample that was 67 false flags out of 97, and eleven seconds of the
    # sixteen the audit took. C5 reports the spellings; this check is about
    # whether the row is in the right class.
    canonical = labels.where(labels.isna(), labels.map(prof.normalise_text))
    counts = canonical.value_counts()
    if len(counts) < 2:
        return _skip("the label has fewer than two classes")

    # Stratified k-fold cannot put a member of a small class in every fold. It
    # fails quietly, so these are removed and named rather than left to break.
    too_small = counts[counts < config.MIN_CLASS_MEMBERS_FOR_CV]
    keep = canonical.notna() & ~canonical.isin(too_small.index)
    if keep.sum() < config.MISLABEL_MIN_ROWS or canonical[keep].nunique() < 2:
        return _skip("too few rows once classes below the fold count were dropped")

    positions = np.flatnonzero(keep.to_numpy())
    X = encoded.X[positions]
    y = canonical.to_numpy()[positions].astype(str)
    # Predictions come back as the settled spelling, so each one is named again
    # with the spelling that class most often uses in the file. Suggesting a row
    # be relabelled to something the column has never contained would be a
    # strange thing to offer.
    spelling = (
        pd.DataFrame({"canonical": canonical[keep], "raw": labels[keep]})
        .groupby("canonical")["raw"]
        .agg(lambda values: values.value_counts().index[0])
        .to_dict()
    )

    proba = cross_val_predict(
        HistGradientBoostingClassifier(random_state=0),
        X, y,
        cv=StratifiedKFold(config.CV_FOLDS, shuffle=True, random_state=0),
        method="predict_proba",
    )
    classes = np.unique(y)
    index_of = {c: i for i, c in enumerate(classes)}

    p_given = proba[np.arange(len(y)), [index_of[v] for v in y]]
    p_top = proba.max(axis=1)
    predicted = classes[proba.argmax(axis=1)]
    cv_accuracy = float((predicted == y).mean())

    flagged = (p_given < config.MISLABEL_P_GIVEN_MAX) & (p_top > config.MISLABEL_P_TOP_MIN)
    dropped = {str(k): int(v) for k, v in too_small.items()}

    if not flagged.any():
        return {"issues": [], "cv_accuracy": cv_accuracy,
                "skipped": [], "dropped_classes": dropped}

    # The gap between what the model believed and what the row claims. Ranking by
    # it puts the rows the model is most sure about at the top of the list.
    noise = (p_top - p_given)[flagged]
    rows = df.index.to_numpy()[positions][flagged]
    # Row index breaks ties. argsort's default is not stable, so rows sharing a
    # noise score came back in a different order on every run, which rewrote the
    # committed fixtures without any finding actually changing.
    order = np.lexsort((rows, -noise))
    rows, noise = rows[order], noise[order]

    share = len(rows) / len(df)
    weak = cv_accuracy < config.WEAK_MODEL_ACCURACY
    severity = MEDIUM if weak or share <= 0.05 else HIGH

    detail = (
        f"{len(rows)} rows carry a label the model disagrees with, having never seen "
        f"those rows during training. "
    )
    if weak:
        detail += (
            f"Cross-validated accuracy is only {cv_accuracy:.2f}, so the model cannot "
            "model this task and these flags are probably noise. Treat the list as "
            "low confidence until the features explain the label better."
        )
    else:
        detail += (
            f"Cross-validated accuracy is {cv_accuracy:.2f}, so the model is worth "
            "listening to. The most confident disagreements are ranked first."
        )
    if dropped:
        names = ", ".join(f"'{spelling.get(k, k)}' ({v} rows)" for k, v in dropped.items())
        detail += f" Classes too small to cross-validate were left out: {names}."

    given = labels.to_numpy()[positions][flagged][order]
    guessed = np.array([spelling.get(c, c) for c in predicted[flagged][order]])
    evidence_rows = [
        {"index": int(i), "given": str(g), "predicted": str(pr), "noise_score": round(float(nz), 4)}
        for i, g, pr, nz in zip(rows[:200], given[:200], guessed[:200], noise[:200])
    ]

    return {
        "issues": [
            make_issue(
                id=f"mislabels:{label_column}", check=CHECK, scope="row",
                severity=severity,
                title=f"{len(rows)} rows have a label the model disagrees with",
                detail=detail, column=label_column, row_indices=rows,
                suggested_action="relabel",
                evidence={
                    "cv_accuracy": cv_accuracy,
                    "low_confidence": weak,
                    "share_of_rows": share,
                    "dropped_classes": dropped,
                    "rows": evidence_rows,
                },
            )
        ],
        "cv_accuracy": cv_accuracy,
        "skipped": [],
        "dropped_classes": dropped,
    }
