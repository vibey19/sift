"""Checks that report a finding but decline to act on it.

Each of these is certain about what it found and uncertain about what should
happen next. Merging two spellings that appear equally often destroys a
distinction; blanking a marker that covers a third of a column erases an answer;
collapsing identical rows in a table with no identifier throws away events;
rewriting 01/02/2023 picks one of two readings at random.

The finding still appears, with its rows and its reasoning. What changes is that
the one-click button leaves it alone, and the detail says why.
"""

import pandas as pd
import pytest

from sift import runner


def audit(df):
    return runner.audit(df)["issues"]


def one(df, check):
    found = [i for i in audit(df) if i["check"] == check]
    assert found, f"{check} did not fire at all"
    return found[0]


def padded(n):
    return [str(i) for i in range(n)]


# --- C5: spellings that might be a distinction -------------------------------

def test_a_lopsided_spelling_is_treated_as_a_typo():
    df = pd.DataFrame({"plan": ["Premium"] * 95 + ["premium"] * 5, "id": padded(100)})
    issue = one(df, "C5_categorical_inconsistency")
    assert issue["evidence"]["auto_apply"] is True
    assert issue["evidence"]["canonical"] == {"Premium": ["Premium", "premium"]}


def test_a_balanced_spelling_is_left_for_the_user():
    # BRCA1 and brca1 in equal numbers are two things, not one thing typed badly.
    df = pd.DataFrame({"gene": ["BRCA1", "brca1"] * 25, "id": padded(50)})
    issue = one(df, "C5_categorical_inconsistency")
    assert issue["evidence"]["auto_apply"] is False
    assert issue["evidence"]["canonical"] == {}
    assert issue["evidence"]["contested"]
    assert "more likely to be a distinction" in issue["detail"]


def test_padding_is_merged_however_the_counts_fall():
    # Surrounding space is never meaningful, so an even split changes nothing.
    df = pd.DataFrame({"plan": [" Premium "] * 50 + ["Premium"] * 50, "id": padded(100)})
    issue = one(df, "C5_categorical_inconsistency")
    assert issue["evidence"]["auto_apply"] is True


def test_the_safe_half_is_still_applied_when_another_group_is_contested():
    df = pd.DataFrame({
        "v": (["Gold"] * 45 + ["gold"] * 2 + ["AB"] * 25 + ["ab"] * 25),
        "id": padded(97),
    })
    issue = one(df, "C5_categorical_inconsistency")
    assert "Gold" in issue["evidence"]["canonical"]
    assert "AB" in issue["evidence"]["contested"] or "ab" in issue["evidence"]["contested"]
    assert issue["evidence"]["auto_apply"] is True


# --- C11: a marker that might be an answer -----------------------------------

def test_a_rare_marker_is_blanked():
    df = pd.DataFrame({"reason": ["UNKNOWN"] * 4 + ["late", "damaged", "wrong"] * 16, "id": padded(52)})
    assert one(df, "C11_sentinel_values")["evidence"]["auto_apply"] is True


def test_a_common_marker_is_left_for_the_user():
    # "Not applicable" is a real answer to "reason for return".
    df = pd.DataFrame({"reason": ["N/A"] * 20 + ["late", "damaged", "wrong"] * 10, "id": padded(50)})
    issue = one(df, "C11_sentinel_values")
    assert issue["evidence"]["auto_apply"] is False
    assert "real answer" in issue["detail"]


# --- D1: rows that might be separate events ----------------------------------

def test_a_few_duplicates_are_removed():
    rows = padded(300) + ["7", "19"]
    df = pd.DataFrame({"id": [f"T{v}" for v in rows], "v": rows})
    assert one(df, "D1_exact_duplicates")["evidence"]["auto_apply"] is True


def test_a_file_that_is_mostly_repetition_is_left_alone():
    # Forty identical coffee sales, and nothing in the row says which sale.
    df = pd.DataFrame({"item": ["coffee"] * 40, "price": ["2"] * 40})
    issue = one(df, "D1_exact_duplicates")
    assert issue["evidence"]["auto_apply"] is False
    assert "separate events" in issue["detail"]


# --- C16: dates that fit two readings ----------------------------------------

def test_dates_are_rewritten_when_the_column_settles_the_order():
    df = pd.DataFrame({"d": [f"{(i % 19) + 10}/0{(i % 9) + 1}/2023" for i in range(40)], "v": padded(40)})
    issue = one(df, "C16_mixed_date_formats")
    assert issue["evidence"]["auto_apply"] is True
    assert issue["evidence"]["dayfirst"] is True


def test_dates_that_fit_both_readings_are_left_for_the_user():
    df = pd.DataFrame({"d": [f"0{(i % 9) + 1}/0{((i + 3) % 9) + 1}/2023" for i in range(40)], "v": padded(40)})
    issue = one(df, "C16_mixed_date_formats")
    assert issue["evidence"]["auto_apply"] is False
    assert "coin flip" in issue["detail"]


# --- the inference bug this work uncovered -----------------------------------

@pytest.mark.parametrize(
    "values,expected",
    [
        ([f"2023-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}" for i in range(300)], "datetime"),
        ([f"2023-04-01 {i // 60:02d}:{i % 60:02d}:00" for i in range(300)], "datetime"),
        ([f"TXN{i:06d}" for i in range(300)], "id_like"),
    ],
)
def test_a_column_of_distinct_dates_is_not_an_identifier(values, expected):
    # One row per day, or per timestamp, makes a date column almost entirely
    # distinct. The identifier test runs first, so it used to win, and every
    # check that cares about dates skipped the column.
    from sift import profile as prof

    assert prof.infer_type(pd.Series(values), len(values)) == expected


def test_a_country_written_in_caps_is_still_that_country():
    # Two systems writing FINLAND and Finland produce an even split that means
    # one country. Balance alone cannot tell that apart from a real distinction;
    # the shape of the value can.
    df = pd.DataFrame({
        "country": ["Finland"] * 40 + ["FINLAND"] * 35 + [" Finland "] * 25,
        "id": padded(100),
    })
    issue = one(df, "C5_categorical_inconsistency")
    assert issue["evidence"]["auto_apply"] is True
    assert issue["evidence"]["contested"] == {}


def test_a_short_code_written_two_ways_is_left_alone():
    df = pd.DataFrame({"code": ["AB"] * 25 + ["ab"] * 25, "id": padded(50)})
    assert one(df, "C5_categorical_inconsistency")["evidence"]["auto_apply"] is False


def test_a_long_label_is_merged_even_when_evenly_split():
    df = pd.DataFrame({
        "answer": ["Strongly agree"] * 25 + ["STRONGLY AGREE"] * 25,
        "id": padded(50),
    })
    assert one(df, "C5_categorical_inconsistency")["evidence"]["auto_apply"] is True


def test_the_boolean_column_belongs_to_one_check_only():
    # Both checks used to fire on Y/yes/TRUE/N/no/FALSE. C17 settled on "false",
    # then C5 merged it back into "FALSE" because that spelling was commoner in
    # the original column, and the better fix lost because it ran first.
    df = pd.DataFrame({
        "active": (["Y", "yes", "TRUE", "N", "no", "FALSE"] * 20),
        "id": padded(120),
    })
    issues = audit(df)
    assert [i for i in issues if i["check"] == "C17_inconsistent_booleans"]
    assert not [
        i for i in issues
        if i["check"] == "C5_categorical_inconsistency" and i["column"] == "active"
    ]
