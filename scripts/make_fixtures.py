"""Capture real API responses into src/fixtures/ for the frontend to build against.

The point is that a frontend bug is never ambiguous. If the UI renders wrong
against a fixture, the UI is wrong, because the fixture came out of the server.

    python scripts/make_fixtures.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))

from sift import runner  # noqa: E402

OUT = ROOT / "src" / "fixtures"

CASES = [
    ("profile_churn", "profile", "churn_dirty", {}),
    ("audit_churn", "audit", "churn_dirty", {"label_column": "churned", "split_column": "split"}),
    ("audit_cafe", "audit", "cafe_dirty", {}),
    # No label chosen: everything label-aware should report itself as skipped
    # rather than silently returning nothing.
    ("audit_no_label", "audit", "churn_dirty", {}),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, kind, sample, kwargs in CASES:
        df = runner.load((ROOT / "public" / "samples" / f"{sample}.csv").read_text())
        payload = runner.profile_payload(df) if kind == "profile" else runner.audit(df, **kwargs)
        path = OUT / f"{name}.json"
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        size = path.stat().st_size / 1024
        summary = (
            f"{payload['n_rows']} rows, {payload['n_cols']} cols"
            if kind == "profile"
            else f"{len(payload['issues'])} issues, cv={payload['summary']['cv_accuracy']}"
        )
        print(f"  {name:18s} {size:6.1f} KB  {summary}")


if __name__ == "__main__":
    main()
