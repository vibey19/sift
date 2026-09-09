"""The parsing contract, shared by the server and the browser.

Two independent CSV parsers were reading the same upload and disagreeing about
what the table was. The server saw `a, a.1, b` where the browser saw `a, a, b`;
blank headers became `Unnamed: 1` on one side and `column_2` on the other; the
server did not recognise a semicolon at all and read the whole file as a single
column. Every fix naming a column the other side called something else was
silently discarded, because looking up a name that does not exist is not an
error, it is just nothing happening.

So the rules live here in one place, and src/parsing.js implements the same ones.
tests/test_parsing.py runs both over the same awkward headers and fails if they
disagree.

The rules:

1. The delimiter is whichever of , ; | tab divides the first lines into the most
   fields, counting only outside quotes, and among equals the one that does it
   on the largest share of lines. A file with no consistent candidate is read as
   commas.
2. Header names are trimmed.
3. A header that is empty after trimming becomes column_N, numbered from 1.
4. A repeated header keeps its first appearance and later ones gain _2, _3, and
   so on, until the name is unique.
5. The header is the first row that is shaped like one: it has as many fields as
   the file generally does, and more than half of them are filled. Rows above it
   are a preamble and are dropped. That covers the title and generated-on lines
   a spreadsheet export puts at the top, and comment lines, without needing a
   rule for either.
6. A header split over two rows, which is what a merged cell in a spreadsheet
   becomes on the way out, is joined into one name per column.
7. Text that was written as UTF-8 and read as Western European is repaired
   before any of the above, because the damage reaches the column names too.
"""

from __future__ import annotations

import re

CANDIDATES = (",", "\t", ";", "|")
SAMPLE_LINES = 20
# A preamble longer than this is not a preamble, it is the file.
MAX_PREAMBLE = 12
# A header can contain a blank name, but not mostly blank names.
MIN_FILLED_HEADER = 0.5

# Windows-1252 for 0x80 to 0x9F, the only range where it differs from Latin-1.
# Written out rather than left to the codec because the codec refuses the five
# codes the table leaves undefined, while every browser decoder passes them
# through as themselves - and a browser decoder is what produced the text this
# function is handed.
CP1252_HIGH = "".join(chr(c) for c in (
    0x20AC, 0x81, 0x201A, 0x192, 0x201E, 0x2026, 0x2020, 0x2021, 0x2C6, 0x2030,
    0x160, 0x2039, 0x152, 0x8D, 0x17D, 0x8F, 0x90, 0x2018, 0x2019, 0x201C,
    0x201D, 0x2022, 0x2013, 0x2014, 0x2DC, 0x2122, 0x161, 0x203A, 0x153, 0x9D,
    0x17E, 0x178,
))
_CP1252_TO_BYTE = {ord(char): 0x80 + index for index, char in enumerate(CP1252_HIGH)}

# Anything that could have come from a single byte. Nothing outside this can be
# part of the damage, so a file with none of it needs no further thought. A
# regular expression rather than a loop: this runs on every upload.
_FROM_A_BYTE = re.compile("[\u0080-\u00ff" + CP1252_HIGH + "]")

_NUMERIC_CELL = re.compile(r"^-?[\d,]*\d(\.\d+)?$")


def split_lines(text: str) -> list[str]:
    """Physical lines, quote-aware, so a quoted newline does not end a row."""
    lines: list[str] = []
    current: list[str] = []
    in_quotes = False
    i = 0
    while i < len(text):
        char = text[i]
        if char == '"':
            # A doubled quote inside a quoted field is an escaped quote.
            if in_quotes and i + 1 < len(text) and text[i + 1] == '"':
                current.append('""')
                i += 2
                continue
            in_quotes = not in_quotes
            current.append(char)
        elif char in "\r\n" and not in_quotes:
            if char == "\r" and i + 1 < len(text) and text[i + 1] == "\n":
                i += 1
            lines.append("".join(current))
            current = []
        else:
            current.append(char)
        i += 1
    if current:
        lines.append("".join(current))
    return lines


def count_outside_quotes(line: str, delimiter: str) -> int:
    total = 0
    in_quotes = False
    for char in line:
        if char == '"':
            in_quotes = not in_quotes
        elif char == delimiter and not in_quotes:
            total += 1
    return total


def _non_ascii(text: str) -> int:
    return sum(1 for c in text if ord(c) > 127)


def _to_bytes(text: str, table: str | None) -> bytes | None:
    """Characters back to the bytes they were decoded from, or None.

    Done with translate and a codec rather than a loop over the characters,
    because this runs over the whole file on every upload and a Python-level
    pass over four megabytes is seconds rather than milliseconds.
    """
    if table is not None:
        text = text.translate(_CP1252_TO_BYTE)
    try:
        return text.encode("latin-1")
    except UnicodeEncodeError:
        return None


def repair_mojibake(text: str) -> str:
    """Undo a file that was written as UTF-8 and read as Western European.

    "café" written as UTF-8 is the two bytes 0xC3 0xA9 where the accent is. Read
    back one byte at a time as Windows-1252 those become "Ã©", and the file now
    genuinely contains that text - no decoder can tell later that it was not
    meant. Every join, every groupby and every exported row carries it.

    The repair is the same trip backwards: write the characters out as
    Windows-1252 and read the bytes as UTF-8. What makes it safe to do unasked
    is that undamaged text almost never survives it. A real "é" is the single
    byte 0xE9, which is not valid UTF-8 on its own, so the attempt fails and the
    text is returned untouched. The count of non-ASCII characters has to fall as
    well, since mojibake always turns one character into two or three.
    """
    if not _FROM_A_BYTE.search(text):
        return text
    for table in (CP1252_HIGH, None):
        # Both tables are tried because both decoders are in use in the wild and
        # they differ over 0x80 to 0x9F, which is where Cyrillic, Greek and
        # Japanese bytes land.
        raw = _to_bytes(text, table)
        if raw is None:
            continue
        try:
            candidate = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        if _non_ascii(candidate) < _non_ascii(text):
            return candidate
    return text


def detect_delimiter(text: str) -> str:
    """The delimiter that divides the sample most consistently.

    Looking only at the header is not enough: a comma inside a quoted heading
    outvotes a real tab. Looking at a sample and requiring agreement between the
    lines is what makes a semicolon file readable.
    """
    lines = [line for line in split_lines(text) if line.strip()][:SAMPLE_LINES]
    if not lines:
        return ","

    best, best_score = ",", (0, 0.0)
    for candidate in CANDIDATES:
        counts = [count_outside_quotes(line, candidate) for line in lines]
        modal = max(set(counts), key=counts.count)
        if modal == 0:
            continue
        agreement = counts.count(modal) / len(counts)
        if agreement < 0.6:
            continue
        # More fields is a better division, and where two candidates divide the
        # file into the same number of fields, the one that does it on more of
        # the lines wins. A file of semicolons whose values contain decimal
        # commas has one comma on most rows and one semicolon on all of them.
        score = (modal, agreement)
        if score > best_score:
            best, best_score = candidate, score
    return best


def normalise_headers(raw: list[str]) -> list[str]:
    """Trimmed, never blank, never repeated."""
    names: list[str] = []
    seen: dict[str, int] = {}
    for position, value in enumerate(raw):
        name = str(value).strip()
        if not name:
            name = f"column_{position + 1}"
        if name in seen:
            seen[name] += 1
            # Keep suffixing until the result is genuinely unused, so a file
            # that already contains "a_2" does not produce a second one.
            candidate = f"{name}_{seen[name]}"
            while candidate in seen:
                seen[name] += 1
                candidate = f"{name}_{seen[name]}"
            name = candidate
        seen[name] = seen.get(name, 1)
        names.append(name)
    return names


def field_width(text: str, delimiter: str) -> int:
    """How many fields the table has, ignoring anything sitting above it.

    Taking the most common count across the whole file breaks both ways: a file
    with two comment lines and two data lines has no majority, and a file with
    one over-long row would let that row widen the table. So each of the first
    few lines is tried as the header, and the first one whose count matches what
    most of the lines below it do is the table. Failing that, the first line is
    the header, because a header is what a first line usually is.
    """
    counts = [
        count_outside_quotes(line, delimiter) + 1
        for line in split_lines(text)
        if line.strip()
    ]
    if not counts:
        return 1

    for index in range(min(len(counts) - 1, MAX_PREAMBLE)):
        below = counts[index + 1 : index + 1 + SAMPLE_LINES]
        if not below:
            break
        modal = max(set(below), key=lambda c: (below.count(c), c))
        if counts[index] == modal:
            return modal
    return counts[0]


def find_header(rows: list[list[str]], width: int) -> int:
    """Index of the first row shaped like a header. 0 when nothing looks better.

    A spreadsheet export often opens with a title, a generated-on line and a
    blank, and a hand-maintained file often opens with comments. All of them are
    narrower or emptier than the table underneath, which is enough to tell them
    apart without a rule for each.
    """
    for index, row in enumerate(rows[:MAX_PREAMBLE]):
        filled = sum(1 for cell in row if str(cell).strip())
        if len(row) >= width and filled / max(width, 1) > MIN_FILLED_HEADER:
            return index
    return 0


def _looks_numeric(cell: str) -> bool:
    text = str(cell).strip()
    return bool(text) and bool(_NUMERIC_CELL.match(text))


def header_span(rows: list[list[str]], width: int, header_at: int) -> int:
    """How many rows the header occupies: 1 normally, 2 when it is split.

    A merged cell in a spreadsheet has no representation in CSV. "Q1" spanning
    two columns comes out as "Q1" followed by a blank, with "revenue" and
    "units" on the row underneath. Read as one header that file has a column
    called nothing and two called "revenue", and read as a header plus a data
    row it has a row of text where the numbers should be.

    The signature is a first row that cannot be the whole header - it leaves a
    column unnamed - above a row that carries no numbers and fills the gap.
    Three further conditions keep an ordinary header with a text row under it
    from being eaten: every column has to end up named, no two columns may end
    up with the same name, and the rows below the pair have to contain a number
    somewhere, so that the row of text above them is visibly not more data. One
    row is not enough to ask that of - the first record in a file is as likely as
    any other to have a gap in it - so the sample is the same twenty lines the
    rest of this module works from. A table that is text all the way down cannot
    be told apart either way, and is left as the single-row header it appears
    to be.
    """
    if header_at + 2 >= len(rows):
        return 1
    top = list(rows[header_at])[:width]
    bottom = list(rows[header_at + 1])[:width]
    if len(top) < width or len(bottom) < width:
        return 1
    if any(_looks_numeric(c) for c in bottom):
        return 1
    if all(str(c).strip() for c in top):
        return 1  # the first row names every column, so it is the whole header

    combined = combine_headers(top, bottom, width)
    if not all(combined) or len(set(combined)) < width:
        return 1
    body = rows[header_at + 2 : header_at + 2 + SAMPLE_LINES]
    if not any(_looks_numeric(c) for row in body for c in list(row)[:width]):
        return 1
    return 2


def combine_headers(top: list[str], bottom: list[str], width: int) -> list[str]:
    """Join a two-row header into one name per column.

    The top row is carried across the blanks a merged cell leaves behind, so
    "Q1, , Q2, " over "revenue, units, revenue, units" becomes "Q1 revenue",
    "Q1 units", "Q2 revenue", "Q2 units".
    """
    names, parent = [], ""
    for index in range(width):
        above = str(top[index]).strip() if index < len(top) else ""
        below = str(bottom[index]).strip() if index < len(bottom) else ""
        if above:
            parent = above
        if parent and below and parent != below:
            names.append(f"{parent} {below}")
        else:
            names.append(below or parent)
    return names
