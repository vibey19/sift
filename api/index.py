import sys
from pathlib import Path

# The handler is loaded as a top-level module by uvicorn and by Vercel's Python
# runtime, neither of which puts this directory on the path. Without it the
# sibling package resolves under pytest and nowhere else.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy
import pandas
import sklearn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from sift import runner

app = FastAPI(title="Sift", docs_url=None, redoc_url=None)


class ProfileRequest(BaseModel):
    csv: str
    delimiter: str | None = None


class AuditRequest(BaseModel):
    csv: str
    delimiter: str | None = None
    label_column: str | None = None
    split_column: str | None = None
    checks: list[str] | None = None


def _load(csv: str, delimiter: str | None):
    try:
        return runner.load(csv, delimiter)
    except runner.InputTooLarge as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Could not read that file: {exc}") from exc


# Routes carry the full /api prefix because vercel.json rewrites /api/(.*) to this
# function without stripping the original path.
@app.get("/api/health")
def health() -> dict:
    # The versions are here so a deploy proves the analytical stack actually
    # imported inside the function, not just that the function booted.
    return {
        "ok": True,
        "versions": {
            "pandas": pandas.__version__,
            "numpy": numpy.__version__,
            "sklearn": sklearn.__version__,
        },
    }


@app.post("/api/profile")
def profile(request: ProfileRequest) -> dict:
    return runner.profile_payload(_load(request.csv, request.delimiter))


@app.post("/api/audit")
def audit(request: AuditRequest) -> dict:
    df = _load(request.csv, request.delimiter)
    return runner.audit(df, request.label_column, request.split_column, request.checks)
