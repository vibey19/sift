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


def number_parts(value) -> dict | None:
    """The number inside a formatted value, and the decoration around it.

    Returns the number as the text it was written as, never as a float. That
    distinction is the whole point of this function. A float cannot hold
    9007199254740993 - it comes back as ...992 - and it cannot hold 007 either,
    because the zeros are not a quantity. Both are ordinary in an id column, and
    both used to be destroyed on export by a reformat that read the value into a
    number and printed it out again. Undressing a number is a string operation
    and is done as one.

    `unit` and `symbol` are what was taken off, so a check can say so rather
    than quietly dropping the kilograms.
    """
    text = str(value).strip()
    if not text:
        return None

    # Accountants write a negative as (1,234.00).
    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1].strip()

    symbols = re.findall(f"[{re.escape(CURRENCY)}]", text)
    text = re.sub(f"[{re.escape(CURRENCY)}]", "", text).strip()
    # Thousands separators only in the strict grouping. "1.234,50" is European
    # for 1234.50 and is refused rather than read as 1.2345.
    grouped = bool(re.match(r"^-?\d{1,3}(,\d{3})+(\.\d+)?\s*", text))
    if grouped:
        text = re.sub(r"(?<=\d),(?=\d{3})", "", text)
    text = text.replace(" ", "") if re.fullmatch(r"-?[\d\s]*\.?\d+", text) else text

    if text.startswith("-") and text[1:2] == " ":
        text = "-" + text[1:].strip()

    text = text.strip()
    match = _NUMBER.match(text)
    if not match:
        return None
    literal = match.group(1)
    unit = text[len(literal):].strip()
    if negative:
        literal = literal[1:] if literal.startswith("-") else "-" + literal
    return {
        "literal": literal,
        "symbol": symbols[0] if symbols else "",
        "unit": unit,
        "negative": negative,
        "grouped": grouped,
    }


def strip_number_formatting(value) -> str | None:
    """The number as text, with the decoration removed and nothing else changed.

    None when the value is not a number. Every digit that was written is still
    there afterwards, including leading zeros and every digit of an integer too
    long for a float.
    """
    parts = number_parts(value)
    return None if parts is None else parts["literal"]


def parse_number(value) -> float | None:
    """A number, however it was written down. None if it is not one.

    Lossy by nature, and used only where a float is what is wanted: deciding
    whether a column is numeric, comparing values, arithmetic. Anything that
    writes a value back into the file uses strip_number_formatting instead.
    """
    literal = strip_number_formatting(value)
    if literal is None:
        return None
    try:
        return float(literal)
    except ValueError:
        return None


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


# --- markup and invisible characters ----------------------------------------
# The named entities worth decoding, written by code point so that no character
# here has to survive a copy and paste to stay correct. The check that reports
# markup and the fix that removes it share this list, so anything missing from
# it is neither flagged nor quietly deleted.
ENTITIES = {
    "amp": "&", "lt": "<", "gt": ">", "quot": '"', "apos": "'", "nbsp": " ",
    "ndash": chr(0x2013), "mdash": chr(0x2014), "hellip": chr(0x2026),
    "lsquo": chr(0x2018), "rsquo": chr(0x2019), "ldquo": chr(0x201C),
    "rdquo": chr(0x201D), "bull": chr(0x2022), "middot": chr(0x00B7),
    "deg": chr(0x00B0), "copy": chr(0x00A9), "reg": chr(0x00AE),
    "trade": chr(0x2122), "euro": chr(0x20AC), "pound": chr(0x00A3),
}

# An opening or closing tag, or an entity from the list above. Deliberately
# narrow: "a < b" and "3 > 2" are not markup and must not be read as it.
_TAG = r"</?[a-zA-Z][a-zA-Z0-9]*(?:\s[^<>]*)?/?>"
_ENTITY = r"&(?:" + "|".join(sorted(ENTITIES)) + r"|#\d{1,5}|#x[0-9a-fA-F]{1,4});"
MARKUP = re.compile(_TAG + "|" + _ENTITY)


def _entity(match: str) -> str:
    body = match[1:-1]
    if body.startswith("#"):
        try:
            return chr(int(body[2:], 16) if body[1:2] in "xX" else int(body[1:]))
        except (ValueError, OverflowError):
            return match
    return ENTITIES.get(body, match)


def strip_markup(value) -> str:
    """Text with the web page taken off it.

    Tags become a space rather than nothing, so that "one<br>two" does not come
    back as a single word, and the run of spaces that leaves is collapsed
    afterwards.
    """
    text = str(value if value is not None else "")
    text = re.sub(_TAG, " ", text)
    text = re.sub(_ENTITY, lambda m: _entity(m.group(0)), text)
    return " ".join(text.split())


# Characters that take up no width and change nothing about what a value means.
ZERO_WIDTH = "".join(chr(c) for c in (0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x200E, 0x200F, 0x00AD))
# Spaces that are not the space character. Folded to one rather than removed,
# because a space is what they are and something meant one to be there.
SPACE_LIKE = "".join(chr(c) for c in (0x00A0, 0x2007, 0x202F, 0x2009, 0x2002, 0x2003))
INVISIBLE = re.compile("[" + ZERO_WIDTH + SPACE_LIKE + "]")


def strip_invisible(value) -> str:
    text = str(value if value is not None else "")
    return "".join("" if c in ZERO_WIDTH else " " if c in SPACE_LIKE else c for c in text)
