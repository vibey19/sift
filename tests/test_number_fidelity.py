"""What a number loses on the way through, and what it must not.

Undressing a number is a string operation and is done as one. Reading it into a
float and printing it back out is what destroys an account number: a float
cannot hold 9007199254740993, so it comes back as ...992, and it cannot hold 007
either, because the leading zeros are not a quantity. Both are ordinary in an id
column and neither is something a user would ever think to check for.

The other half of this file is about meaning rather than digits. Taking 'kg' off
a value is the only thing the one-click path does that cannot be undone by
looking at the result, so a column carrying two different units is reported and
left alone, and a column carrying one says which one it dropped.
"""

import json
import os
import subprocess
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from sift import formats

ROOT = Path(__file__).resolve().parent.parent


def audit(df):
    from sift import runner

    return runner.audit(df)["issues"]


def find(issues, check, column=None):
    out = [i for i in issues if i["check"] == check]
    return [i for i in out if i["column"] == column] if column else out


def padding(n=60):
    return [str(i) for i in range(n)]


# --- digits ------------------------------------------------------------------

@pytest.mark.parametrize(
    "written,bare",
    [
        # The two that were being destroyed.
        ("9007199254740993", "9007199254740993"),
        ("1234567890123456789", "1234567890123456789"),
        ("007", "007"),
        ("0012.50", "0012.50"),
        # And the same numbers with formatting on them, which does come off.
        ("$9,007,199,254,740,993", "9007199254740993"),
        ("$1,234.56", "1234.56"),
        ("($500.00)", "-500.00"),
        ("(1,000)", "-1000"),
        ("12.5%", "12.5"),
        ("45 kg", "45"),
        ("21.3 C", "21.3"),
        ("  7  ", "7"),
        ("-999", "-999"),
        # Not numbers, and not to be mangled into ones.
        ("abc", None),
        ("12 apples", None),
        ("--", None),
        ("", None),
        # European decimal comma stays refused rather than read as 1.2345.
        ("2.500,50", None),
    ],
)
def test_taking_the_formatting_off_keeps_every_digit(written, bare):
    assert formats.strip_number_formatting(written) == bare


def test_a_long_integer_survives_the_export_that_used_to_shorten_it():
    # Through the browser, which is where the damage happened: the value was
    # read into a Number and printed back out.
    script = """
import { parseCsv, toCsv } from './src/csv.js'
import { replay, REFORMAT_NUMBER } from './src/edits.js'
const parsed = parseCsv(process.env.SIFT_CSV)
const out = replay(parsed.columns, parsed.rows,
  parsed.columns.map((c) => ({ op: REFORMAT_NUMBER, column: c })))
console.log(JSON.stringify({ csv: toCsv(out.columns, out.rows) }))
"""
    csv = 'account,code,price\n9007199254740993,007,"$1,234.56"\n1234567890123456789,012,"$99.00"\n'
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, cwd=ROOT, check=True,
        env={**os.environ, "SIFT_CSV": csv},
    )
    out = json.loads(result.stdout)["csv"]
    assert "9007199254740993" in out
    assert "1234567890123456789" in out
    assert ",007," in out and ",012," in out
    # The money still had its formatting taken off.
    assert "1234.56" in out


def test_parse_number_is_still_the_lossy_one():
    # It is allowed to lose precision, because it exists to answer "is this a
    # number" and to do arithmetic. Nothing that writes a value uses it.
    assert formats.parse_number("9007199254740993") == 9007199254740992.0
    assert formats.parse_number("007") == 7.0


# --- meaning -----------------------------------------------------------------

def test_a_column_of_two_units_is_not_flattened_into_one():
    df = pd.DataFrame({
        "weight": [f"{v} kg" if v % 2 else f"{v} lb" for v in range(60)],
        "n": padding(),
    })
    found = find(audit(df), "C15_formatted_numbers", "weight")
    assert found
    assert found[0]["evidence"]["auto_apply"] is False
    assert found[0]["evidence"]["units"] == ["kg", "lb"]
    assert "which was which" in found[0]["detail"]


def test_two_currencies_in_one_column_are_the_same_problem():
    df = pd.DataFrame({
        "price": [f"${v}.50" if v % 2 else f"€{v}.50" for v in range(60)],
        "n": padding(),
    })
    found = find(audit(df), "C15_formatted_numbers", "price")
    assert found and found[0]["evidence"]["auto_apply"] is False
    assert "currencies" in found[0]["title"]


def test_one_consistent_unit_is_removed_and_named():
    df = pd.DataFrame({"weight": [f"{v} kg" for v in range(60)], "n": padding()})
    found = find(audit(df), "C15_formatted_numbers", "weight")
    assert found
    assert found[0]["evidence"]["auto_apply"] is True
    assert found[0]["evidence"]["units"] == ["kg"]
    assert "'kg'" in found[0]["detail"]


def test_the_percent_convention_is_stated_rather_than_assumed():
    # 45% becomes 45 and not 0.45. Both conventions are common and the choice
    # is invisible in the result, so it is said out loud instead.
    df = pd.DataFrame({"rate": [f"{v / 2}%" for v in range(60)], "n": padding()})
    found = find(audit(df), "C15_formatted_numbers", "rate")
    assert found and found[0]["evidence"]["percent"] is True
    assert "not 0.45" in found[0]["detail"]


# --- coincidence -------------------------------------------------------------

def test_an_arithmetic_rule_confirmed_four_ways_is_not_applied():
    # Two columns drawn from {1, 2} produce four distinct facts however many
    # rows they fill, and c = a * b holding across all four is a coincidence
    # waiting to happen. Forty rows of it used to clear the support threshold
    # and fill cells unasked.
    rng = np.random.default_rng(0)
    a = rng.integers(1, 3, 40)
    b = rng.integers(1, 3, 40)
    c = (a * b).astype(object)
    c[3] = ""
    df = pd.DataFrame({"a": a, "b": b, "c": c, "d": rng.integers(1, 50, 40)}).astype(str)

    found = find(audit(df), "C13_arithmetic_relation", "c")
    assert found
    assert found[0]["evidence"]["auto_apply"] is False
    assert found[0]["evidence"]["distinct_inputs"] == 4
    assert "hold by accident" in found[0]["detail"]


def test_a_rule_confirmed_many_ways_still_fills():
    rng = np.random.default_rng(0)
    qty = rng.integers(1, 10, 200)
    price = rng.choice([2.5, 3.5, 2.0, 3.0, 4.0, 5.5, 7.25], 200)
    total = np.round(qty * price, 2).astype(object)
    total[::20] = ""
    df = pd.DataFrame({
        "qty": qty, "price": price, "total": total,
        "x": rng.uniform(0, 9, 200).round(2),
    }).astype(str)

    found = find(audit(df), "C13_arithmetic_relation", "total")
    assert found
    assert found[0]["evidence"]["auto_apply"] is True
    assert found[0]["evidence"]["distinct_inputs"] > 12
