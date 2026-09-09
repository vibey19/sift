"""CSV loading, missing-value policy and column type inference.

Everything downstream reads types from here, so the inference order is fixed and
first match wins. Getting it wrong is not a subtle failure: an id column typed as
numeric drags a correlation check into nonsense, and a numeric column typed as
categorical produces a one-hot matrix with three thousand columns.
"""

from __future__ import annotations

import io
import unicodedata

import numpy as np
import pandas as pd

from . import config

CONSTANT = "constant"
ID_LIKE = "id_like"
BOOLEAN = "boolean"
DATETIME = "datetime"
NUMERIC = "numeric"
TEXT = "text"
CATEGORICAL = "categorical"

_BOOLEAN_VALUES = {"0", "1", "true", "false", "yes", "no", "y", "n", "t", "f"}
# A date needs a separator. Without this guard pandas happily reads 20240101 and
# even bare years as timestamps, and every integer column becomes a date.
_DATE_HINTS = ("-", "/", ":")


def load_csv(text: str, delimiter: str | None = None) -> pd.DataFrame:
    if delimiter is None:
        delimiter = "\t" if "\t" in text.split("\n", 1)[0] else ","
    # Everything arrives as a string and this module decides what is missing.
    # pandas' default na_values would silently turn "N/A" and "none" into NaN,
    # which is exactly the evidence C4 and C5 exist to report.
    return pd.read_csv(
        io.StringIO(text),
        delimiter=delimiter,
        dtype=str,
        keep_default_na=False,
        na_values=[],
        skip_blank_lines=True,
    )


def normalise_text(value: str) -> str:
    # NFKD splits accented characters so the combining marks can be dropped,
    # which is what makes "Café" and "Cafe" group together in C5.
    stripped = unicodedata.normalize("NFKD", str(value))
    stripped = "".join(c for c in stripped if not unicodedata.combining(c))
    return " ".join(stripped.split()).lower()


def missing_mask(s: pd.Series) -> pd.Series:
    return s.isna() | s.fillna("").map(lambda v: normalise_text(v) in config.MISSING_TOKENS)


def present(s: pd.Series) -> pd.Series:
    return s[~missing_mask(s)]


def non_empty(s: pd.Series) -> pd.Series:
    # Only a truly blank cell counts as absent here. C4 needs to see "N/A" as a
    # non-numeric string, because that is why its column will not parse.
    return s[s.notna() & (s.str.strip() != "")]


def as_numeric(s: pd.Series) -> pd.Series:
    return pd.to_numeric(present(s).str.replace(",", "", regex=False), errors="coerce")


def as_datetime(s: pd.Series) -> pd.Series:
    values = present(s)
    if values.empty:
        return pd.Series(dtype="datetime64[ns]")
    if not values.str.contains("|".join(map(pd.io.common.re.escape, _DATE_HINTS))).any():
        return pd.Series(index=values.index, dtype="datetime64[ns]")
    return pd.to_datetime(values, errors="coerce", format="mixed")


def _numeric_share(s: pd.Series) -> float:
    values = present(s)
    return 0.0 if values.empty else float(as_numeric(s).notna().mean())


def infer_type(s: pd.Series, n_rows: int) -> str:
    values = present(s)
    n_unique = int(values.nunique())

    if n_unique <= 1:
        return CONSTANT

    mean_tokens = float(values.str.split().str.len().mean()) if not values.empty else 0.0
    numeric_share = _numeric_share(s)
    numeric = as_numeric(s).dropna()
    # An integer column of distinct values is an identifier. A continuous
    # measurement is also mostly distinct but is a genuine feature, so the
    # fractional part is what separates them.
    looks_continuous = (
        numeric_share > config.NUMERIC_PARSE_FRACTION
        and not numeric.empty
        and float((numeric % 1 != 0).mean()) > 0.05
    )
    # Uniqueness is measured over the values that are actually there. A column
    # that is 40% blank but distinct wherever it is filled is still an id, and
    # dividing by the row count would hide that.
    unique_share = n_unique / len(values) if len(values) else 0.0
    # Free text is near-unique by nature, so uniqueness alone would classify
    # every review body as an identifier. An id is a short token, not a sentence.
    if (
        unique_share > config.ID_UNIQUE_FRACTION
        and not looks_continuous
        and mean_tokens < config.TEXT_MIN_MEAN_TOKENS
    ):
        return ID_LIKE

    if n_unique == 2 and set(values.str.strip().str.lower().unique()) <= _BOOLEAN_VALUES:
        return BOOLEAN

    parsed = as_datetime(s)
    if not parsed.empty and float(parsed.notna().mean()) > config.DATETIME_PARSE_FRACTION:
        return DATETIME

    if numeric_share > config.NUMERIC_PARSE_FRACTION:
        return NUMERIC

    if mean_tokens >= config.TEXT_MIN_MEAN_TOKENS:
        return TEXT

    return CATEGORICAL


def profile_column(name: str, s: pd.Series, n_rows: int) -> dict:
    missing = missing_mask(s)
    values = s[~missing]
    kind = infer_type(s, n_rows)

    found_tokens = (
        values.iloc[0:0]
        if values.empty
        else s[missing].dropna().map(normalise_text).value_counts()
    )
    profile = {
        "name": name,
        "inferred_type": kind,
        "n_missing": int(missing.sum()),
        "n_present": int(len(values)),
        "missing_fraction": float(missing.mean()) if n_rows else 0.0,
        "n_unique": int(values.nunique()),
        # Share of the filled cells that are distinct, which is what makes a
        # column an identifier. Measured over filled cells, not all rows.
        "unique_share": float(values.nunique() / len(values)) if len(values) else 0.0,
        "sample_values": values.drop_duplicates().head(5).tolist(),
        # Which spellings of "missing" this column actually used. Users are
        # routinely surprised that their export wrote three different ones.
        "missing_tokens": {k: int(v) for k, v in found_tokens.items() if k != ""},
    }

    if kind == NUMERIC:
        numeric = as_numeric(s).dropna()
        if not numeric.empty:
            profile["stats"] = {
                "min": float(numeric.min()),
                "max": float(numeric.max()),
                "mean": float(numeric.mean()),
                "median": float(numeric.median()),
            }
    elif kind in (CATEGORICAL, BOOLEAN, CONSTANT):
        profile["top_values"] = {
            str(k): int(v) for k, v in values.value_counts().head(10).items()
        }
    elif kind == TEXT:
        profile["mean_tokens"] = float(values.str.split().str.len().mean())

    return profile


def profile_frame(df: pd.DataFrame) -> list[dict]:
    return [profile_column(c, df[c], len(df)) for c in df.columns]


def types_by_column(profiles: list[dict]) -> dict[str, str]:
    return {p["name"]: p["inferred_type"] for p in profiles}


def numeric_frame(df: pd.DataFrame, types: dict[str, str]) -> pd.DataFrame:
    cols = [c for c in df.columns if types.get(c) == NUMERIC]
    return pd.DataFrame({c: as_numeric(df[c]).reindex(df.index) for c in cols})
