"""Orchestration. Loads the CSV, profiles it, runs the checks, sorts the result."""

from __future__ import annotations

import pandas as pd

from . import config, profile as prof
from .checks import columns, dataset
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
    issues = [
        *dataset.run(df, profiles, label_column),
        *columns.run(df, profiles, label_column),
    ]
    if checks:
        issues = [i for i in issues if i["check"] in set(checks)]
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
            "cv_accuracy": None,
            "skipped_checks": [],
        },
    }
