"""Orchestration. Loads the CSV, profiles it, runs the checks, sorts the result."""

from __future__ import annotations

import pandas as pd

from . import config, encode, profile as prof
from .checks import columns, dataset, rows
from .issue import sort_issues


class InputTooLarge(ValueError):
    pass


def load(csv: str, delimiter: str | None = None) -> pd.DataFrame:
    df = prof.load_csv(csv, delimiter)
    if len(df) > config.MAX_ROWS:
        raise InputTooLarge(
            f"{len(df)} rows exceeds the {config.MAX_ROWS} row limit. "
            "Sample the file down and audit the sample."
        )
    if len(df.columns) > config.MAX_COLS:
        raise InputTooLarge(
            f"{len(df.columns)} columns exceeds the {config.MAX_COLS} column limit."
        )
    return df


def profile_payload(df: pd.DataFrame) -> dict:
    return {
        "n_rows": len(df),
        "n_cols": len(df.columns),
        "columns": prof.profile_frame(df),
        "preview": df.head(20).fillna("").to_dict(orient="records"),
    }


def audit(
    df: pd.DataFrame,
    label_column: str | None = None,
    split_column: str | None = None,
    checks: list[str] | None = None,
) -> dict:
    profiles = prof.profile_frame(df)
    # Built once and handed to D2, D4, C10 and R1. Encoding the frame separately
    # per check would let them disagree about whether two rows are the same.
    encoded = encode.build(df, profiles, label_column, split_column)

    dataset_issues, dataset_skipped = dataset.run(df, profiles, label_column, split_column)
    column_issues, column_skipped = columns.run(df, profiles, label_column, split_column)
    mislabels = rows.run(df, encoded, label_column)

    issues = [*dataset_issues, *column_issues, *mislabels["issues"]]
    skipped = [*dataset_skipped, *column_skipped, *mislabels["skipped"]]

    if checks:
        wanted = set(checks)
        issues = [i for i in issues if i["check"] in wanted]
    issues = sort_issues(issues)

    affected: set[int] = set()
    for issue in issues:
        affected.update(issue["row_indices"])

    return {
        "issues": issues,
        "summary": {
            "high": sum(i["severity"] == "high" for i in issues),
            "medium": sum(i["severity"] == "medium" for i in issues),
            "low": sum(i["severity"] == "low" for i in issues),
            "rows_affected": len(affected),
            # Surfaced next to the flags on purpose. A list of suspicious rows
            # means nothing until you know the model could learn the task.
            "cv_accuracy": mislabels["cv_accuracy"],
            "skipped_checks": skipped,
        },
    }
