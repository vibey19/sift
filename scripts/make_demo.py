"""Trim a real audit down to what the landing page demo needs.

The landing page shows genuine findings from samples/churn_dirty.csv rather than
invented copy. The full response is 60KB, which has no business in a marketing
bundle, so this keeps the fields the demo renders and drops the rest.

    python scripts/make_demo.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

from sift import runner  # noqa: E402

SHOW = [
    "C10_leakage",
    "D4_train_test_overlap",
    "R1_mislabels",
    "D2_near_duplicates",
    "C5_categorical_inconsistency",
    "C7_outliers",
]


def main() -> None:
    df = runner.load((ROOT / "public" / "samples" / "churn_dirty.csv").read_text())
    result = runner.audit(df, label_column="churned", split_column="split")
    by_check = {i["check"]: i for i in result["issues"]}

    issues = []
    for check in SHOW:
        issue = by_check.get(check)
        if not issue:
            continue
        issues.append(
            {
                "id": issue["id"],
                "check": issue["check"],
                "severity": issue["severity"],
                "title": issue["title"],
                "detail": issue["detail"],
                "column": issue["column"],
                "total_affected": issue["total_affected"],
                # Enough rows to make the list feel real, not enough to bloat it.
                "row_indices": issue["row_indices"][:8],
            }
        )

    payload = {
        "dataset": "churn_dirty.csv",
        "n_rows": len(df),
        "n_cols": len(df.columns),
        "cv_accuracy": result["summary"]["cv_accuracy"],
        "high": result["summary"]["high"],
        "medium": result["summary"]["medium"],
        "low": result["summary"]["low"],
        "rows_affected": result["summary"]["rows_affected"],
        "issues": issues,
    }
    out = ROOT / "src" / "demo.json"
    out.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"  demo.json  {out.stat().st_size / 1024:.1f} KB  {len(issues)} issues")


if __name__ == "__main__":
    main()
