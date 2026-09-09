"""CSV loading, missing-value policy and column type inference.

Everything downstream reads types from here, so the inference order is fixed and
first match wins. Getting it wrong is not a subtle failure: an id column typed as
numeric drags a correlation check into nonsense, and a numeric column typed as
categorical produces a one-hot matrix with three thousand columns.
"""

from __future__ import annotations

import io
import re
import unicodedata

import pandas as pd

from . import config, formats, parsing

CONSTANT = "constant"
ID_LIKE = "id_like"
BOOLEAN = "boolean"
DATETIME = "datetime"
NUMERIC = "numeric"
TEXT = "text"
CATEGORICAL = "categorical"

_BOOLEAN_VALUES = {"0", "1", "true", "false", "yes", "no", "y", "n", "t", "f"}
# 14:30:00 is a time of day or an elapsed duration, and pandas reads it as that
# time today. Either way it is not a date, and treating it as one invents a date
# that is not in the file and changes every day the file is opened.
_TIME_ONLY = re.compile(r"^\d{1,4}:\d{1,2}(:\d{1,2}(\.\d+)?)?$")
# A date needs a separator. Without this guard pandas happily reads 20240101 and
# even bare years as timestamps, and every integer column becomes a date.
_DATE_HINTS = ("-", "/", ":")


def _pad_or_trim(width: int):
    # Rows with the wrong number of fields are ordinary in exported CSVs, and the
    # browser already pads and trims them before showing a row count. The server
    # has to agree, or a file the user can see on screen is rejected on upload.
    def fix(fields: list[str]) -> list[str]:
        if len(fields) < width:
            return fields + [""] * (width - len(fields))
        return fields[:width]

    return fix


def load_csv(text: str, delimiter: str | None = None) -> pd.DataFrame:
    if delimiter is None:
        delimiter = parsing.detect_delimiter(text)

    # Line endings are normalised first. pandas' python engine does not treat a
    # lone carriage return as a line ending, and older Mac exports still use one.
    # Splitting is quote-aware, so a carriage return inside a quoted field is
    # left where it is, which is what the browser does too.
    text = "\n".join(parsing.split_lines(text))
    width = parsing.field_width(text, delimiter)

    # Read with neither a header nor a column count of pandas' choosing. The
    # header is found below, because line one is often a title, a generated-on
    # stamp or a comment, and a spreadsheet export usually has all three.
    #
    # Everything arrives as a string and this module decides what is missing.
    # pandas' default na_values would turn "N/A" and "none" into NaN, which is
    # exactly the evidence C4 and C11 exist to report.
    options = dict(
        delimiter=delimiter,
        dtype=str,
        header=None,
        names=range(width),
        keep_default_na=False,
        na_values=[],
        skip_blank_lines=True,
        engine="python",
        on_bad_lines=_pad_or_trim(width),
    )
    try:
        raw = pd.read_csv(io.StringIO(text), **options)
    except (pd.errors.EmptyDataError, StopIteration):
        return pd.DataFrame()

    if raw.empty:
        return pd.DataFrame()

    rows = raw.fillna("").astype(str).values.tolist()
    header_at = parsing.find_header(rows, width)
    frame = raw.iloc[header_at + 1:].reset_index(drop=True)
    frame.columns = parsing.normalise_headers(list(raw.iloc[header_at]))
    return frame


def normalise_text(value: str) -> str:
    # NFKD splits accented characters so the combining marks can be dropped,
    # which is what makes "Café" and "Cafe" group together in C5.
    stripped = unicodedata.normalize("NFKD", str(value))
    stripped = "".join(c for c in stripped if not unicodedata.combining(c))
    return " ".join(stripped.split()).lower()


def is_sentinel(s: pd.Series) -> pd.Series:
    return s.fillna("").map(lambda v: normalise_text(v) in config.SENTINEL_TOKENS)


def without_sentinels(df: pd.DataFrame) -> pd.DataFrame:
    """A copy where words meaning "missing" are actually missing.

    Relationships between columns are invisible until this is done. "Every item
    has one price" is false while ERROR is one of the items, so a check looking
    for that rule sees nothing and the user is told to fix the sentinels first
    and come back. One pass should find everything.
    """
    out = df.copy()
    for col in out.columns:
        out.loc[is_sentinel(out[col]), col] = ""
    return out


def missing_mask(s: pd.Series) -> pd.Series:
    return s.isna() | s.fillna("").map(lambda v: normalise_text(v) in config.MISSING_TOKENS)


def present(s: pd.Series) -> pd.Series:
    return s[~missing_mask(s)]


def non_empty(s: pd.Series) -> pd.Series:
    # Only a truly blank cell counts as absent here. C4 needs to see "N/A" as a
    # non-numeric string, because that is why its column will not parse.
    return s[s.notna() & (s.str.strip() != "")]


# Only a comma used as a thousands separator, in the strict grouping a US-style
# number uses. Stripping commas unconditionally turns the European "1.234,50",
# which means one thousand two hundred and thirty four, into 1.2345 - a silent
# error of three orders of magnitude that then flows into every numeric check.
# Where the meaning is ambiguous the value is refused rather than guessed at.
_GROUPED = re.compile(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$")


def _degroup(value: str) -> str:
    return value.replace(",", "") if _GROUPED.match(value.strip()) else value


def as_numeric(s: pd.Series) -> pd.Series:
    return pd.to_numeric(present(s).map(_degroup), errors="coerce")


def is_time_only(s: pd.Series) -> bool:
    values = present(s)
    if values.empty:
        return False
    return float(values.str.strip().str.match(_TIME_ONLY).mean()) > 0.9


def as_datetime(s: pd.Series) -> pd.Series:
    values = present(s)
    if values.empty:
        return pd.Series(dtype="datetime64[ns]")
    if is_time_only(values):
        return pd.Series(index=values.index, dtype="datetime64[ns]")
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
    def _continuous(series: pd.Series) -> bool:
        return not series.empty and float((series % 1 != 0).mean()) > 0.05

    looks_continuous = numeric_share > config.NUMERIC_PARSE_FRACTION and _continuous(numeric)
    if not looks_continuous and len(values):
        # A column of money is every value distinct and none of them parsing,
        # which is exactly what an identifier looks like from here. What tells
        # them apart is the formatting itself: an identifier does not carry a
        # currency symbol, a percent sign or a unit. Continuity is no help,
        # because round amounts have no fractional part to vary.
        # Sentinels are excluded from the ratio. A handful of ERROR values in a
        # column of money is not evidence that the column is an identifier, but
        # counted against it they drag the share below the threshold and the
        # whole column is misread.
        readable = values[~is_sentinel(values)]
        dressed = readable.map(formats.needs_reformatting)
        if len(readable) and float(dressed.mean()) > config.NUMERIC_PARSE_FRACTION:
            looks_continuous = True
    # Uniqueness is measured over the values that are actually there. A column
    # that is 40% blank but distinct wherever it is filled is still an id, and
    # dividing by the row count would hide that.
    # A column of dates is nearly all distinct by nature, and the identifier
    # test runs first, so one row per day or per timestamp would be read as an
    # id and skipped by every check that cares about dates.
    parsed_dates = as_datetime(s)
    is_dates = (
        not parsed_dates.empty
        and float(parsed_dates.notna().mean()) > config.DATETIME_PARSE_FRACTION
    )

    unique_share = n_unique / len(values) if len(values) else 0.0
    # Free text is near-unique by nature, so uniqueness alone would classify
    # every review body as an identifier. An id is a short token, not a sentence.
    if (
        unique_share > config.ID_UNIQUE_FRACTION
        and not looks_continuous
        and not is_dates
        and mean_tokens < config.TEXT_MIN_MEAN_TOKENS
    ):
        return ID_LIKE

    if n_unique == 2 and set(values.str.strip().str.lower().unique()) <= _BOOLEAN_VALUES:
        return BOOLEAN

    if is_dates:
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
