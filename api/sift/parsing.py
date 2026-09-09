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
"""

from __future__ import annotations

CANDIDATES = (",", "\t", ";", "|")
SAMPLE_LINES = 20
# A preamble longer than this is not a preamble, it is the file.
MAX_PREAMBLE = 12
# A header can contain a blank name, but not mostly blank names.
MIN_FILLED_HEADER = 0.5


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
