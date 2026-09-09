"""Reading values that are numbers, dates or booleans wearing formatting.

A column of money is a column of numbers with a currency symbol in front, commas
inside and sometimes brackets around the negatives. A column of dates is often
three date formats stacked on top of each other because three people maintained
it. None of that survives a cast, and all of it is mechanical to undo.

Every parser here has a twin in src/formats.js. The server decides whether a
column can be read this way; the browser does the rewriting. A test asserts the
two agree on a shared list of awkward values, because a disagreement would mean
the preview and the exported file disagree too.
"""

from __future__ import annotations

import re

CURRENCY = "$€£¥₹₽¢"
# Deliberately short. Longer suffixes are usually words, and a word after a
# number is more likely a category than a unit.
UNIT = r"[a-zA-Z°%/²³]{0,4}"

_NUMBER = re.compile(rf"^(-?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*{UNIT}$")

MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    )
}

TRUE_WORDS = frozenset({"true", "t", "yes", "y", "1", "on"})
FALSE_WORDS = frozenset({"false", "f", "no", "n", "0", "off"})


def parse_number(value) -> float | None:
    """A number, however it was written down. None if it is not one."""
    text = str(value).strip()
    if not text:
        return None

    # Accountants write a negative as (1,234.00).
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1].strip()

    text = re.sub(f"[{re.escape(CURRENCY)}]", "", text).strip()
    # Thousands separators only in the strict grouping. "1.234,50" is European
    # for 1234.50 and is refused rather than read as 1.2345.
    if re.match(r"^-?\d{1,3}(,\d{3})+(\.\d+)?\s*", text):
        text = re.sub(r"(?<=\d),(?=\d{3})", "", text)
    text = text.replace(" ", "") if re.fullmatch(r"-?[\d\s]*\.?\d+", text) else text

    if text.startswith("-") and text[1:2] == " ":
        text = "-" + text[1:].strip()

    match = _NUMBER.match(text.strip())
    if not match:
        return None
    try:
        number = float(match.group(1))
    except ValueError:
        return None
    return -number if negative else number


def needs_reformatting(value) -> bool:
    """True when the value is a number that will not parse as written."""
    text = str(value).strip()
    if not text:
        return False
    try:
        float(text)
        return False
    except ValueError:
        return parse_number(text) is not None


def parse_date(value, dayfirst: bool = False) -> str | None:
    """An ISO date, from the handful of formats people actually type."""
    text = str(value).strip()
    if not text:
        return None

    iso = re.match(r"^(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    if iso:
        y, m, d = (int(g) for g in iso.groups())
        return _iso(y, m, d)

    numeric = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$", text)
    if numeric:
        a, b, y = (int(g) for g in numeric.groups())
        # A value above 12 can only be the day, whichever order was intended.
        if a > 12:
            return _iso(y, b, a)
        if b > 12:
            return _iso(y, a, b)
        return _iso(y, b, a) if dayfirst else _iso(y, a, b)

    named = re.match(r"^(\d{1,2})[-\s]([A-Za-z]{3,9})[-\s,]+(\d{4})$", text)
    if named:
        d, name, y = named.groups()
        month = MONTHS.get(name[:3].lower())
        return _iso(int(y), month, int(d)) if month else None

    named2 = re.match(r"^([A-Za-z]{3,9})[-\s]+(\d{1,2})[-\s,]+(\d{4})$", text)
    if named2:
        name, d, y = named2.groups()
        month = MONTHS.get(name[:3].lower())
        return _iso(int(y), month, int(d)) if month else None

    return None


def _iso(year: int, month: int, day: int) -> str | None:
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def date_style(value) -> str | None:
    """Which of the shapes above a value is written in."""
    text = str(value).strip()
    if not text:
        return None
    if re.match(r"^\d{4}[-/]\d{1,2}[-/]\d{1,2}", text):
        return "iso"
    if re.match(r"^\d{1,2}[-/.]\d{1,2}[-/.]\d{4}$", text):
        return "numeric"
    if re.match(r"^\d{1,2}[-\s][A-Za-z]{3,9}[-\s,]+\d{4}$", text):
        return "day-month-name"
    if re.match(r"^[A-Za-z]{3,9}[-\s]+\d{1,2}[-\s,]+\d{4}$", text):
        return "month-name-day"
    return None


def needs_dayfirst(values) -> bool:
    """Whether d/m/y is the only reading that fits the whole column."""
    for value in values:
        match = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.]\d{4}$", str(value).strip())
        if match and int(match.group(1)) > 12:
            return True
    return False


def parse_boolean(value) -> bool | None:
    text = str(value).strip().lower()
    if text in TRUE_WORDS:
        return True
    if text in FALSE_WORDS:
        return False
    return None
