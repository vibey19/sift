"""The parsing contract, and proof that both implementations honour it.

The server and the browser each parse the uploaded file. If they disagree about
the delimiter, the column names or the row count, then the server reports a
finding about a column the browser cannot find, and the fix for it is silently
discarded - looking up a missing name is not an error, it is just nothing
happening. That failure leaves no trace anywhere.

The last test here is the one that matters: it runs both parsers over the same
corpus of awkward files and compares everything they produce.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

from sift import parsing, profile as prof

ROOT = Path(__file__).resolve().parent.parent

# Files chosen to break a naive parser: quoted delimiters, repeated and blank
# headings, padding, every delimiter, ragged rows, and a quoted newline.
CORPUS = {
    "plain comma": "a,b\n1,2\n3,4\n",
    "tab": "a\tb\n1\t2\n3\t4\n",
    "semicolon": "a;b\n1;2\n3;4\n",
    "pipe": "a|b\n1|2\n3|4\n",
    "duplicate headers": "a,a,b\n1,2,3\n4,5,6\n",
    "triple duplicate": "a,a,a\n1,2,3\n",
    "blank header": "a,,b\n1,2,3\n",
    "all blank headers": ",,\n1,2,3\n",
    "padded headers": "  a  ,  b  \n1,2\n",
    "padded and duplicate": " a , a \n1,2\n",
    "header that collides with the suffix": "a,a,a_2\n1,2,3\n",
    "quoted delimiter in header": '"a,b";c\n1;2\n3;4\n',
    "quoted delimiter in data": 'a,b\n"x,y",2\n"p,q",4\n',
    "quoted newline": 'a,b\n"line\none",2\n"z",3\n',
    "doubled quotes": 'a,b\n"she said ""hi""",2\n',
    "crlf": "a,b\r\n1,2\r\n3,4\r\n",
    "cr only": "a,b\r1,2\r3,4\r",
    "trailing newline": "a,b\n1,2",
    "blank line in the middle": "a,b\n1,2\n\n3,4\n",
    "ragged short": "a,b,c\n1,2\n3,4,5\n",
    "ragged long": "a,b\n1,2,3\n4,5\n",
    "single column": "a\n1\n2\n",
    "header only": "a,b\n",
    "unicode headers": "café,naïve\n1,2\n",
    "semicolon with comma decimals": "amt;n\n1,50;2\n3,25;4\n",
}


@pytest.mark.parametrize(
    "text,expected",
    [
        ("a,b\n1,2\n", ","),
        ("a\tb\n1\t2\n", "\t"),
        ("a;b\n1;2\n", ";"),
        ("a|b\n1|2\n", "|"),
        # A comma inside a quoted heading must not outvote the real delimiter.
        ('"a,b";c\n1;2\n', ";"),
        # Commas in the data, semicolons dividing it.
        ("amt;n\n1,50;2\n3,25;4\n", ";"),
        ("", ","),
        ("just one column\nvalue\n", ","),
    ],
)
def test_delimiter_is_read_from_the_whole_sample(text, expected):
    assert parsing.detect_delimiter(text) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        (["a", "b"], ["a", "b"]),
        (["  a  ", " b "], ["a", "b"]),
        (["a", "a"], ["a", "a_2"]),
        (["a", "a", "a"], ["a", "a_2", "a_3"]),
        (["", "b"], ["column_1", "b"]),
        (["a", "", ""], ["a", "column_2", "column_3"]),
        # The suffix must not collide with a name that is already there.
        (["a", "a_2", "a"], ["a", "a_2", "a_3"]),
        ([" a ", "a"], ["a", "a_2"]),
    ],
)
def test_headers_are_trimmed_filled_and_made_unique(raw, expected):
    assert parsing.normalise_headers(raw) == expected


def test_a_semicolon_file_is_not_read_as_one_column():
    # The regression that started this: the server only ever looked for a tab
    # or a comma, so a European export arrived as a single column of text.
    frame = prof.load_csv("a;b;c\n1;2;3\n")
    assert list(frame.columns) == ["a", "b", "c"]
    assert frame.shape == (1, 3)


def test_repeated_headers_do_not_become_pandas_names():
    # "a.1" is pandas' invention and the browser would never produce it.
    frame = prof.load_csv("a,a,b\n1,2,3\n")
    assert list(frame.columns) == ["a", "a_2", "b"]


def test_the_two_parsers_agree_on_every_file_in_the_corpus():
    script = """
import { parseCsv } from './src/csv.js'
const corpus = JSON.parse(process.env.SIFT_CORPUS)
const out = {}
for (const [name, text] of Object.entries(corpus)) {
  const { columns, rows, delimiter } = parseCsv(text)
  out[name] = { columns, rows, delimiter }
}
console.log(JSON.stringify(out))
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, cwd=ROOT, check=True,
        env={**os.environ, "SIFT_CORPUS": json.dumps(CORPUS)},
    )
    browser = json.loads(result.stdout)

    mismatches = []
    for name, text in CORPUS.items():
        frame = prof.load_csv(text)
        server_columns = list(frame.columns)
        server_rows = frame.fillna("").astype(str).values.tolist()
        theirs = browser[name]

        if parsing.detect_delimiter(text) != theirs["delimiter"]:
            mismatches.append(f"{name}: delimiter {parsing.detect_delimiter(text)!r} vs {theirs['delimiter']!r}")
        if server_columns != theirs["columns"]:
            mismatches.append(f"{name}: columns {server_columns} vs {theirs['columns']}")
        elif server_rows != theirs["rows"]:
            mismatches.append(
                f"{name}: {len(server_rows)} rows vs {len(theirs['rows'])}"
                + (f", first difference {next((a, b) for a, b in zip(server_rows, theirs['rows']) if a != b)}"
                   if len(server_rows) == len(theirs["rows"]) else "")
            )

    assert not mismatches, "the two parsers disagree:\n  " + "\n  ".join(mismatches)
