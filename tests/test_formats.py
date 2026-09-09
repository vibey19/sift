"""The parsers, and the promise that the two implementations of them agree.

api/sift/formats.py decides whether a column can be read as numbers or dates.
src/formats.js does the rewriting in the browser. If they disagree, the server
promises a fix the browser then applies differently, and the preview and the
exported file quietly diverge. The last test in this file runs both against the
same awkward values and compares.
"""

import json
import os
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from sift import formats

ROOT = Path(__file__).resolve().parent.parent

NUMBERS = [
    ("$1,234.56", 1234.56),
    ("($500.00)", -500.0),
    ("(1,000)", -1000.0),
    ("12.5%", 12.5),
    ("21.3 C", 21.3),
    ("45 kg", 45.0),
    ("-999", -999.0),
    ("€2.500,", None),  # a European decimal comma is ambiguous, so it is refused
    ("1.5e3", 1500.0),
    ("  7  ", 7.0),
    ("abc", None),
    ("", None),
    ("12 apples", None),  # a word, not a unit
    ("--", None),
]

DATES = [
    ("2023-04-05", False, "2023-04-05"),
    ("05/04/2023", True, "2023-04-05"),
    ("04/05/2023", False, "2023-04-05"),
    ("25/12/2023", False, "2023-12-25"),  # 25 can only be the day
    ("Apr 5, 2023", False, "2023-04-05"),
    ("5-Apr-2023", False, "2023-04-05"),
    ("not a date", False, None),
    ("", False, None),
]

BOOLEANS = [("Y", True), ("yes", True), ("TRUE", True), ("1", True), ("on", True),
            ("N", False), ("no", False), ("FALSE", False), ("0", False), ("maybe", None)]

MARKUP = [
    ("Great <b>product</b> &amp; fast", "Great product & fast"),
    ("one<br>two", "one two"),
    ("<p class=\"lead\">hello</p>", "hello"),
    ("&#8212; and &#x2014;", chr(0x2014) + " and " + chr(0x2014)),
    ("&nbsp;&nbsp;spaced&nbsp;", "spaced"),
    # Not markup, and must survive untouched.
    ("a < b and 3 > 2", "a < b and 3 > 2"),
    ("AT&T and R&D", "AT&T and R&D"),
    ("&someunknownthing;", "&someunknownthing;"),
    ("", ""),
]

INVISIBLE = [
    ("Lon" + chr(0x200B) + "don", "London"),
    ("New" + chr(0x00A0) + "York", "New York"),
    (chr(0xFEFF) + "id", "id"),
    ("soft" + chr(0x00AD) + "break", "softbreak"),
    ("nothing wrong here", "nothing wrong here"),
    ("", ""),
]


@pytest.mark.parametrize("text,expected", NUMBERS)
def test_numbers_are_read_through_their_formatting(text, expected):
    assert formats.parse_number(text) == expected


@pytest.mark.parametrize("text,dayfirst,expected", DATES)
def test_dates_are_read_in_the_formats_people_type(text, dayfirst, expected):
    assert formats.parse_date(text, dayfirst) == expected


@pytest.mark.parametrize("text,expected", BOOLEANS)
def test_booleans_are_read_in_every_spelling(text, expected):
    assert formats.parse_boolean(text) == expected


@pytest.mark.parametrize("text,expected", MARKUP)
def test_markup_comes_off_and_nothing_else_does(text, expected):
    assert formats.strip_markup(text) == expected


@pytest.mark.parametrize("text,expected", INVISIBLE)
def test_invisible_characters_come_out(text, expected):
    assert formats.strip_invisible(text) == expected


def test_a_plain_number_is_not_reported_as_needing_work():
    assert not formats.needs_reformatting("42")
    assert not formats.needs_reformatting("3.14")
    assert formats.needs_reformatting("$42")
    assert formats.needs_reformatting("42%")


def test_day_first_is_decided_by_the_whole_column():
    # One value above 12 in the first position settles it for every other row.
    assert formats.needs_dayfirst(["01/02/2023", "25/03/2023"])
    assert not formats.needs_dayfirst(["01/02/2023", "03/04/2023"])


def test_the_python_and_javascript_parsers_agree():
    cases = {
        "numbers": [text for text, _ in NUMBERS],
        "dates": [[text, first] for text, first, _ in DATES],
        "booleans": [text for text, _ in BOOLEANS],
        "bare": [text for text, _ in NUMBERS] + [
            "9007199254740993", "1234567890123456789", "007", "0012.50",
            "$9,007,199,254,740,993", "2.500,50",
        ],
        "markup": [text for text, _ in MARKUP],
        "invisible": [text for text, _ in INVISIBLE],
    }
    script = """
import { parseNumber, parseDate, parseBoolean, stripMarkup, stripInvisible, stripNumberFormatting } from './src/formats.js'
const cases = JSON.parse(process.env.SIFT_CASES)
console.log(JSON.stringify({
  numbers: cases.numbers.map((v) => parseNumber(v)),
  dates: cases.dates.map(([v, f]) => parseDate(v, f)),
  booleans: cases.booleans.map((v) => parseBoolean(v)),
  bare: cases.bare.map(stripNumberFormatting),
  markup: cases.markup.map(stripMarkup),
  invisible: cases.invisible.map(stripInvisible),
}))
"""
    # Passed through the environment rather than argv, because argv indices
    # shift under `node -e` and the payload contains characters a shell would
    # take an interest in.
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, cwd=ROOT, check=True,
        env={**os.environ, "SIFT_CASES": json.dumps(cases)},
    )
    js = json.loads(result.stdout)

    assert js["numbers"] == [expected for _, expected in NUMBERS]
    assert js["dates"] == [expected for _, _, expected in DATES]
    assert js["booleans"] == [expected for _, expected in BOOLEANS]
    # The textual stripping has to agree too, digit for digit. The server
    # decides a column is numeric; the browser is what writes the file.
    assert js["bare"] == [formats.strip_number_formatting(v) for v in cases["bare"]]
    assert js["markup"] == [expected for _, expected in MARKUP]
    assert js["invisible"] == [expected for _, expected in INVISIBLE]


def audit(df):
    from sift import runner

    return runner.audit(df)["issues"]


def test_c15_reads_a_column_of_money():
    df = pd.DataFrame({
        "amount": [f"${v:,.2f}" for v in range(1000, 1060)],
        "note": [str(i) for i in range(60)],
    })
    found = [i for i in audit(df) if i["check"] == "C15_formatted_numbers"]
    assert found and found[0]["column"] == "amount"
    assert found[0]["suggested_action"] == "reformat_number"


def test_c15_leaves_a_column_of_words_alone():
    df = pd.DataFrame({"city": ["Tampere", "Helsinki", "Turku"] * 20, "n": [str(i) for i in range(60)]})
    assert not [i for i in audit(df) if i["check"] == "C15_formatted_numbers" and i["column"] == "city"]


def test_c16_reports_a_column_written_several_ways():
    dates = ["2023-01-%02d" % (d + 1) for d in range(20)]
    mixed = [d if i % 2 else f"{d[8:10]}/{d[5:7]}/{d[0:4]}" for i, d in enumerate(dates)]
    df = pd.DataFrame({"when": mixed * 3, "n": [str(i) for i in range(60)]})
    found = [i for i in audit(df) if i["check"] == "C16_mixed_date_formats"]
    assert found and len(found[0]["evidence"]["styles"]) == 2


def test_c17_reports_five_spellings_of_true():
    df = pd.DataFrame({
        "active": (["Y", "yes", "TRUE", "N", "no", "FALSE"] * 10),
        "n": [str(i) for i in range(60)],
    })
    found = [i for i in audit(df) if i["check"] == "C17_inconsistent_booleans"]
    assert found and found[0]["evidence"]["distinct"] == 6


def test_c17_ignores_a_column_already_written_one_way():
    df = pd.DataFrame({"active": ["true", "false"] * 30, "n": [str(i) for i in range(60)]})
    assert not [i for i in audit(df) if i["check"] == "C17_inconsistent_booleans"]


def test_c18_finds_a_number_standing_in_for_no_reading():
    values = [f"{20 + (i % 7) * 0.5}" for i in range(200)]
    for i in range(0, 40, 2):
        values[i] = "-999"
    df = pd.DataFrame({"temperature": values, "n": [str(i) for i in range(200)]})
    found = [i for i in audit(df) if i["check"] == "C18_out_of_band_code"]
    assert found, "-999 repeated 20 times should not read as a temperature"
    assert found[0]["evidence"]["code"] == -999.0


def test_c18_does_not_accuse_an_ordinary_repeated_value():
    # Zero appearing often in a column of small numbers is data, not a code.
    values = ["0"] * 60 + [str(i % 9) for i in range(140)]
    df = pd.DataFrame({"count": values, "n": [str(i) for i in range(200)]})
    assert not [i for i in audit(df) if i["check"] == "C18_out_of_band_code"]


def test_a_column_of_money_is_not_mistaken_for_an_identifier():
    # Every formatted value is distinct and none of them parse, which is what an
    # identifier looks like until you read through the formatting.
    from sift import profile as prof

    money = pd.Series([f"${v:,.2f}" for v in range(1000, 1200)])
    assert prof.infer_type(money, len(money)) != prof.ID_LIKE


EUROPEAN = ["1.234,50", "1.000,50", "2.500,00", "1,5"]


@pytest.mark.parametrize("text", EUROPEAN)
def test_a_european_decimal_is_refused_rather_than_misread(text):
    # "1.234,50" means one thousand two hundred and thirty four. Stripping the
    # comma reads it as 1.2345, an error of three orders of magnitude that then
    # flows silently into every numeric check. Ambiguity is refused instead.
    from sift import profile as prof

    assert formats.parse_number(text) is None
    assert pd.isna(prof.as_numeric(pd.Series([text])).iloc[0])


@pytest.mark.parametrize(
    "text,expected",
    [("1,234.50", 1234.5), ("1,000", 1000.0), ("12,345,678", 12345678.0), ("1234.5", 1234.5)],
)
def test_grouped_thousands_still_read_correctly(text, expected):
    from sift import profile as prof

    assert formats.parse_number(text) == expected
    assert prof.as_numeric(pd.Series([text])).iloc[0] == expected


def test_a_timestamp_is_not_truncated_to_a_date():
    # Rewriting "2023-04-01 14:30:00" to "2023-04-01" would throw away the time
    # without saying so. The date check leaves timestamps alone.
    stamps = [f"2023-04-{d:02d} 14:{d:02d}:00" for d in range(1, 29)]
    df = pd.DataFrame({"when": stamps, "v": [str(i) for i in range(28)]})
    assert not [i for i in audit(df) if i["check"] == "C16_mixed_date_formats"]
