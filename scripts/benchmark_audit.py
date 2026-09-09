"""Run the audit over every benchmark dataset and save the responses."""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))
warnings.filterwarnings("ignore")

from sift import runner  # noqa: E402

DIR = ROOT / "benchmark"


def main() -> None:
    manifest = json.loads((DIR / "manifest.json").read_text())
    for name in manifest:
        df = runner.load((DIR / f"{name}_dirty.csv").read_text())
        result = runner.audit(df)
        (DIR / f"{name}_audit.json").write_text(json.dumps(result))
        print(f"  {name:20s} {len(result['issues']):3d} issues")


if __name__ == "__main__":
    main()
