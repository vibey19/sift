import gzip
import logging
import os
import sys
import zlib
from pathlib import Path

# The handler is loaded as a top-level module by uvicorn and by Vercel's Python
# runtime, neither of which puts this directory on the path. Without it the
# sibling package resolves under pytest and nowhere else.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy
import pandas
import sklearn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from sift import runner

app = FastAPI(title="Sift", docs_url=None, redoc_url=None)

# The page and the API are served from different hosts now, so the browser will
# not call one from the other without being told it is allowed.
#
# The default is every origin, and that is not the oversight it looks like.
# There is no session, no cookie and no credential of any kind here: the API
# reads a CSV out of the request body, answers, and forgets it. An origin
# restriction protects a user from their own browser being used against a
# service they are logged into, and there is nothing here to be logged into.
# Set SIFT_ALLOWED_ORIGINS to a comma-separated list to narrow it anyway.
_origins = [o.strip() for o in os.getenv("SIFT_ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Sift-Compression"],
    max_age=86400,
)


@app.exception_handler(Exception)
def unhandled(request: Request, exc: Exception) -> JSONResponse:
    # A bare 500 tells the user nothing and tells whoever is debugging it less.
    # The type and message are enough to act on and carry no data from the file.
    logging.getLogger("sift").exception("unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={
            "detail": (
                f"The audit failed with {type(exc).__name__}. This is a bug in Sift rather "
                "than a problem with your file. Nothing was stored."
            )
        },
    )


class ProfileRequest(BaseModel):
    csv: str
    delimiter: str | None = None


class AuditRequest(BaseModel):
    csv: str
    delimiter: str | None = None
    label_column: str | None = None
    split_column: str | None = None
    checks: list[str] | None = None


# The platform caps a request body at 4.5MB, which is thirty to fifty thousand
# rows of CSV and well under the row limit the checks themselves impose. CSV is
# mostly repeated separators and short tokens, so it compresses about eight to
# one, and sending it compressed is the difference between refusing a file and
# auditing it. The browser gzips anything worth gzipping and says so in a header
# of its own; Content-Encoding is left alone because it describes what the
# network did rather than what the client chose to do.
COMPRESSION_HEADER = "x-sift-compression"


async def _payload(request: Request, model: type[BaseModel]):
    raw = await request.body()
    if request.headers.get(COMPRESSION_HEADER) == "gzip":
        try:
            raw = gzip.decompress(raw)
        except (OSError, EOFError, zlib.error) as exc:
            raise HTTPException(
                status_code=400,
                detail="The request body said it was gzipped and could not be read as gzip.",
            ) from exc
    try:
        return model.model_validate_json(raw)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=f"Malformed request: {exc.error_count()} problems") from exc


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
async def profile(request: Request) -> dict:
    body: ProfileRequest = await _payload(request, ProfileRequest)
    return runner.profile_payload(_load(body.csv, body.delimiter))


@app.post("/api/audit")
async def audit(request: Request) -> dict:
    body: AuditRequest = await _payload(request, AuditRequest)
    df = _load(body.csv, body.delimiter)
    return runner.audit(df, body.label_column, body.split_column, body.checks)
