"""What arrives when the file was not written in the encoding we assume.

Two separate faults live here and they are often confused. The first is a file
whose bytes are not UTF-8: UTF-16 out of Excel's "Unicode Text" option, or a
Latin-1 export. Nothing in the string layer can help with that, because the
browser has already replaced every byte it could not read by the time any of
this code runs, so it is handled in src/decode.js before the text exists.

The second is a file whose bytes are UTF-8 that something already read as
Latin-1 and wrote back out. That damage is genuinely in the file: "cafe" with an
acute accent is stored as two characters that both display. Nothing downstream
can tell it was not meant, so it is undone in the parser, on both sides.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

from sift import parsing, profile as prof

ROOT = Path(__file__).resolve().parent.parent

# Windows-1252 for the range where it differs from Latin-1, so a test can write
# out the exact string a mis-decoding produces rather than trusting a paste.
CP1252_HIGH = [
    0x20AC, 0x81, 0x201A, 0x192, 0x201E, 0x2026, 0x2020, 0x2021, 0x2C6, 0x2030,
    0x160, 0x2039, 0x152, 0x8D, 0x17D, 0x8F, 0x90, 0x2018, 0x2019, 0x201C,
    0x201D, 0x2022, 0x2013, 0x2014, 0x2DC, 0x2122, 0x161, 0x203A, 0x153, 0x9D,
    0x17E, 0x178,
]


def mangle(text: str, table=CP1252_HIGH) -> str:
    """What `text` looks like after being written as UTF-8 and read as 1252."""
    out = []
    for byte in text.encode("utf-8"):
        out.append(chr(table[byte - 0x80]) if table and 0x80 <= byte <= 0x9F else chr(byte))
    return "".join(out)


INTACT = [
    "Cafe Munchen",  # nothing to do
    "Café München",
    "naïve, £5, 20°C",
    "École à Montréal",
    "Здравствуй мир",
    "こんにちは世界",
    "São Paulo, Brasil",
]


@pytest.mark.parametrize("text", INTACT)
def test_a_mis_decoded_string_is_put_back(text):
    assert parsing.repair_mojibake(mangle(text)) == text


@pytest.mark.parametrize("text", INTACT)
def test_text_that_was_never_damaged_is_left_alone(text):
    # This is the property that makes the repair safe to run unasked. A real
    # accented character is a single byte that is not valid UTF-8 on its own, so
    # the round trip fails and the value comes back untouched.
    assert parsing.repair_mojibake(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "",
        "plain ascii only",
        "A-1, A-2, A-3",
        "price in £ and €",
        # Latin-1 text that happens to contain the lead character. It cannot
        # round trip, so it survives.
        "Ãngstrom",
    ],
)
def test_nothing_else_is_touched(text):
    assert parsing.repair_mojibake(text) == text


def test_the_damage_is_repaired_in_the_column_names_too():
    # The one that matters. A column named with the damage in it is a column the
    # browser and the server would both find, agree on, and name wrongly, and
    # every fix aimed at it would be aimed at the wrong string.
    frame = prof.load_csv(mangle("país,año\nEspaña,2024\nPerú,2023\n"))
    assert list(frame.columns) == ["país", "año"]
    assert frame.iloc[0].tolist() == ["España", "2024"]


def test_a_cyrillic_file_comes_back_through_latin_1():
    # Windows-1252 leaves five codes undefined and Cyrillic UTF-8 uses them, so
    # this file only survives the second table the repair tries.
    text = "город,n\nМосква,1\n"
    broken = text.encode("utf-8").decode("latin-1")
    assert list(prof.load_csv(broken).columns) == ["город", "n"]


def _node(script: str, payload: dict) -> dict:
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, cwd=ROOT, check=True,
        env={**os.environ, "SIFT_CASES": json.dumps(payload)},
    )
    return json.loads(result.stdout)


def test_both_parsers_repair_the_same_strings_the_same_way():
    cases = [mangle(t) for t in INTACT] + INTACT + ["plain", "Ãngstrom", ""]
    js = _node(
        """
import { repairMojibake } from './src/parsing.js'
const cases = JSON.parse(process.env.SIFT_CASES).cases
console.log(JSON.stringify({ out: cases.map(repairMojibake) }))
""",
        {"cases": cases},
    )
    assert js["out"] == [parsing.repair_mojibake(c) for c in cases]


def test_the_browser_decoder_reads_the_encodings_a_spreadsheet_writes():
    # decode.js has no Python counterpart - only the browser ever holds bytes -
    # so it is exercised from here rather than left untested.
    js = _node(
        """
import { decodeBytes } from './src/decode.js'
const { text } = JSON.parse(process.env.SIFT_CASES)
const out = {}
const encoders = {
  'utf-8': (s) => new TextEncoder().encode(s),
  'utf-8-bom': (s) => Uint8Array.from([0xef, 0xbb, 0xbf, ...new TextEncoder().encode(s)]),
  'utf-16le-bom': (s) => {
    const bytes = [0xff, 0xfe]
    for (const c of s) { const n = c.codePointAt(0); bytes.push(n & 0xff, n >> 8) }
    return Uint8Array.from(bytes)
  },
  'utf-16le': (s) => {
    const bytes = []
    for (const c of s) { const n = c.codePointAt(0); bytes.push(n & 0xff, n >> 8) }
    return Uint8Array.from(bytes)
  },
  'utf-16be-bom': (s) => {
    const bytes = [0xfe, 0xff]
    for (const c of s) { const n = c.codePointAt(0); bytes.push(n >> 8, n & 0xff) }
    return Uint8Array.from(bytes)
  },
  'latin-1': (s) => Uint8Array.from([...s].map((c) => c.charCodeAt(0))),
}
for (const [name, encode] of Object.entries(encoders)) {
  const result = decodeBytes(encode(text).buffer)
  out[name] = { text: result.text, encoding: result.encoding }
}
console.log(JSON.stringify(out))
""",
        {"text": "name,city\nJosé,Málaga\n"},
    )
    wanted = "name,city\nJosé,Málaga\n"
    for label, result in js.items():
        assert result["text"] == wanted, f"{label} decoded to {result['text']!r}"
    assert js["utf-8"]["encoding"] == "utf-8"
    assert js["utf-16le-bom"]["encoding"] == "utf-16le"
    assert js["utf-16le"]["encoding"] == "utf-16le"  # found without a mark
    assert js["utf-16be-bom"]["encoding"] == "utf-16be"
    assert js["latin-1"]["encoding"] == "windows-1252"
