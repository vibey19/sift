"""Dataset-level checks. D1 and D3 here; D2 and D4 need the shared encoder."""

from __future__ import annotations

import pandas as pd

from .. import config, profile as prof
from ..issue import LOW, MEDIUM, make_issue, pct


def _exact_duplicates(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    duplicated = df.duplicated(keep=False)
    if not duplicated.any():
        return []
    rows = df.index[duplicated]
    n_groups = int(df[duplicated].groupby(list(df.columns), dropna=False).ngroups)
    extra = len(rows) - n_groups
    return [
        make_issue(
            id="exact_duplicates", check="D1_exact_duplicates", scope="dataset",
            severity=MEDIUM,
            title=f"{len(rows)} rows are exact duplicates",
            detail=(
                f"{len(rows)} rows fall into {n_groups} groups of identical records, "
                f"{extra} of them redundant. Duplicates weight those records more heavily "
                "during training and inflate any score computed over them."
            ),
            row_indices=rows, suggested_action="dedupe",
            evidence={"n_groups": n_groups, "n_redundant": extra},
        )
    ]


def _class_imbalance(df: pd.DataFrame, label_column: str | None) -> list[dict]:
    if not label_column or label_column not in df.columns:
        return []
    labels = prof.present(df[label_column])
    counts = labels.value_counts()
    if len(counts) < 2:
        return []

    smallest, n_smallest = counts.index[-1], int(counts.iloc[-1])
    share = n_smallest / len(labels)
    if share >= config.MIN_CLASS_FRACTION and n_smallest >= config.MIN_CLASS_ROWS:
        return []

    # Below the fold count, stratified cross-validation cannot place a member of
    # the class in every fold, so the label-aware checks quietly drop it.
    severity = MEDIUM if n_smallest < config.CV_FOLDS else LOW
    detail = (
        f"'{smallest}' has {n_smallest} rows, {pct(share)} of the labelled data. "
    )
    detail += (
        f"That is fewer than the {config.CV_FOLDS} cross-validation folds, so the "
        "mislabel and leakage checks will drop this class rather than score it."
        if severity == MEDIUM
        else "A model will learn to ignore it and still look accurate."
    )
    return [
        make_issue(
            id=f"imbalance:{label_column}", check="D3_class_imbalance", scope="dataset",
            severity=severity,
            title=f"Smallest class in '{label_column}' is {pct(share)} of rows",
            detail=detail, column=label_column,
            row_indices=df.index[labels.eq(smallest).reindex(df.index, fill_value=False)],
            suggested_action="review",
            evidence={"counts": {str(k): int(v) for k, v in counts.items()}},
        )
    ]


def run(df: pd.DataFrame, profiles: list[dict], label_column: str | None = None) -> list[dict]:
    return [*_exact_duplicates(df), *_class_imbalance(df, label_column)]
