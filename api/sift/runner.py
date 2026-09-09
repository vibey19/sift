"""Orchestration. Loads the CSV, profiles it, runs the checks, sorts the result."""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from . import config, encode, profile as prof
from .checks import columns, dataset, rows
from .issue import sort_issues


log = logging.getLogger("sift")


class InputTooLarge(ValueError):
    pass


def _attempt(name: str, fn, fallback):
    """Run a group of checks, and report a failure instead of losing the audit.

    A dataset that breaks one check should still get the other fourteen. Before
    this, an unhandled error anywhere in the pipeline returned a 500 and the user
    got nothing back, including no clue which check was responsible.
    """
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - deliberately broad, see docstring
        log.exception("check group %s failed", name)
        return fallback(f"{type(exc).__name__}: {exc}")


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
    encoded = _attempt(
        "encode",
        lambda: encode.build(df, profiles, label_column, split_column),
        lambda why: encode.Encoded(np.empty((len(df), 0))),
    )

    dataset_issues, dataset_skipped = _attempt(
        "dataset",
        lambda: dataset.run(df, profiles, label_column, split_column),
        lambda why: ([], [{"check": "dataset checks", "reason": f"failed to run - {why}"}]),
    )
    column_issues, column_skipped = _attempt(
        "columns",
        lambda: columns.run(df, profiles, label_column, split_column),
        lambda why: ([], [{"check": "column checks", "reason": f"failed to run - {why}"}]),
    )
    mislabels = _attempt(
        "rows",
        lambda: rows.run(df, encoded, label_column),
        lambda why: {
            "issues": [],
            "cv_accuracy": None,
            "skipped": [{"check": "R1_mislabels", "reason": f"failed to run - {why}"}],
        },
    )

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
