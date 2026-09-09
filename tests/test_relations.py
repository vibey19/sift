"""C11, C12, C13 and C14 - the checks that make the one-click fix worth pressing.

These are held to a stricter standard than the rest of the tool. A check that
fills a cell is writing data the user did not write, so each one has a test that
it fires when the rule is exact and a test that it stays quiet when it is not.
"""

import numpy as np
import pandas as pd
import pytest

def audit(df, label=None, split=None):
    from sift import runner

    return runner.audit(df, label_column=label, split_column=split)["issues"]


def find(issues, check, column=None):
    out = [i for i in issues if i["check"] == check]
    return [i for i in out if i["column"] == column] if column else out


@pytest.fixture
def sales():
    # Price is a property of the item; total is quantity times price. Both rules
    # are exact, and gaps are left where each can be recovered.
    rng = np.random.default_rng(0)
    menu = {"Coffee": 2.0, "Cake": 3.0, "Tea": 1.5, "Salad": 5.0}
    items = rng.choice(list(menu), 400)
    qty = rng.integers(1, 6, 400)
    price = np.array([menu[i] for i in items])
    df = pd.DataFrame(
        {
            "item": items,
            "quantity": [str(q) for q in qty],
            "price": [f"{p}" for p in price],
            "total": [f"{q * p}" for q, p in zip(qty, price)],
            "channel": rng.choice(["web", "shop"], 400),
        }
    )
    df.loc[0:19, "price"] = ""  # recoverable from item
    df.loc[20:39, "total"] = ""  # recoverable by multiplication
    df.loc[40:59, "quantity"] = ""  # recoverable by division
    df.loc[60:79, "channel"] = "UNKNOWN"  # a sentinel, not a channel
    return df


def test_c11_finds_words_that_mean_missing(sales):
    found = find(audit(sales), "C11_sentinel_values", "channel")
    assert found, "UNKNOWN was not recognised as a missing marker"
    assert found[0]["suggested_action"] == "blank_values"
    assert "UNKNOWN" in found[0]["evidence"]["forms"]
    assert found[0]["total_affected"] == 20


def test_c11_leaves_a_column_that_is_mostly_the_marker_alone():
    # A column that is nearly all "unknown" is a column about not knowing.
    df = pd.DataFrame({"status": ["unknown"] * 90 + ["known"] * 10, "n": [str(i) for i in range(100)]})
    assert not find(audit(df), "C11_sentinel_values", "status")


def test_c12_recovers_a_value_that_another_column_determines(sales):
    found = find(audit(sales), "C12_functional_dependency", "price")
    assert found
    assert found[0]["evidence"]["source"] == "item"
    assert found[0]["total_affected"] == 20
    assert found[0]["evidence"]["mapping"]["Coffee"] == "2.0"


def test_c12_excludes_a_key_that_contradicts_itself():
    # "b" is seen with two different prices, so it cannot be used to fill one in.
    # "a" is consistent across 29 rows and still can.
    df = pd.DataFrame(
        {
            "item": ["a"] * 30 + ["b"] * 30,
            "price": ["1"] * 30 + ["2"] * 29 + ["9"],
            "note": [str(i) for i in range(60)],
        }
    )
    df.loc[0, "price"] = ""

    found = find(audit(df), "C12_functional_dependency", "price")
    assert found, "the consistent key should still be usable"
    mapping = found[0]["evidence"]["mapping"]
    assert mapping == {"a": "1"}, f"a contradictory key leaked into the mapping: {mapping}"


def test_c12_stays_quiet_when_most_of_the_key_is_ambiguous():
    # Only one of four keys settles on an answer. That is a coincidence, not a
    # property of the data, and filling from it would be guessing.
    item, price = [], []
    for name, prices in [("a", ["1"] * 20), ("b", ["2"] * 10 + ["3"] * 10),
                         ("c", ["4"] * 10 + ["5"] * 10), ("d", ["6"] * 10 + ["7"] * 10)]:
        item += [name] * 20
        price += prices
    df = pd.DataFrame({"item": item, "price": price, "note": [str(i) for i in range(80)]})
    df.loc[0, "price"] = ""
    assert not find(audit(df), "C12_functional_dependency", "price")


def test_c12_will_use_the_unambiguous_half_of_a_key():
    # Two items share a price, the rest do not. The unambiguous ones are still a
    # lookup; the shared one is left alone.
    items = ["Cookie"] * 20 + ["Tea"] * 20 + ["Cake"] * 20 + ["Juice"] * 20
    price = ["1"] * 20 + ["1.5"] * 20 + ["3"] * 20 + ["3"] * 20
    df = pd.DataFrame({"item": items, "price": price, "pad": ["x"] * 80})
    df.loc[[0, 21], "item"] = ""

    found = find(audit(df), "C12_functional_dependency", "item")
    assert found, "no partial dependency was found"
    mapping = found[0]["evidence"]["mapping"]
    assert mapping["1"] == "Cookie" and mapping["1.5"] == "Tea"
    assert "3" not in mapping, "the shared price should not resolve to one item"


def test_c13_finds_the_formula_and_solves_it_for_every_term(sales):
    found = find(audit(sales), "C13_arithmetic_relation")
    filled = {i["column"]: i["evidence"] for i in found}

    assert "total" in filled and filled["total"]["operation"] == "product"
    assert "quantity" in filled and filled["quantity"]["operation"] == "quotient"
    for evidence in filled.values():
        assert "total" in evidence["formula"]


def test_c13_ignores_a_relation_that_merely_correlates():
    rng = np.random.default_rng(1)
    a = rng.integers(1, 50, 200)
    b = rng.integers(1, 50, 200)
    noisy = a * b + rng.integers(0, 3, 200)  # close, but not exact
    df = pd.DataFrame({"a": a.astype(str), "b": b.astype(str), "c": noisy.astype(str)})
    df.loc[0:9, "c"] = ""
    assert not find(audit(df), "C13_arithmetic_relation")


def test_c13_does_not_divide_by_zero():
    df = pd.DataFrame({"a": ["0"] * 60, "b": [str(i) for i in range(60)], "c": ["0"] * 60})
    df.loc[0:4, "b"] = ""
    issues = find(audit(df), "C13_arithmetic_relation")
    for issue in issues:
        assert issue["evidence"].get("operation") != "quotient" or issue["total_affected"] >= 0


def test_c14_finds_padding_everywhere_not_just_in_categories():
    df = pd.DataFrame({"n": [" 1", "2 ", "3"] * 20, "s": ["a", "b", "c"] * 20})
    found = find(audit(df), "C14_untrimmed")
    assert found and found[0]["suggested_action"] == "trim"
    assert "n" in found[0]["evidence"]["columns"]


def test_c4_no_longer_repeats_what_c11_reports(sales):
    # Sentinels are C11's job. Reporting them as mixed types too gives the user
    # the same cells twice under two names.
    issues = audit(sales)
    mixed = {i["column"] for i in issues if i["check"] == "C4_mixed_types"}
    assert "channel" not in mixed


def test_relations_see_through_sentinels():
    # The rule "every item has one price" is invisible while ERROR is an item.
    df = pd.DataFrame(
        {
            "item": (["Coffee"] * 30 + ["Cake"] * 30 + ["ERROR"] * 8),
            "price": (["2"] * 30 + ["3"] * 30 + ["9"] * 8),
            "pad": ["x"] * 68,
        }
    )
    df.loc[0:4, "price"] = ""
    assert find(audit(df), "C12_functional_dependency", "price"), (
        "the dependency should be found in one pass, not after fixing sentinels"
    )


def test_missing_categories_get_an_action_and_numbers_do_not():
    df = pd.DataFrame({"cat": ["a", "b", ""] * 40, "num": ["1", "", "3"] * 40})
    issues = find(audit(df), "C1_missingness")
    actions = {i["column"]: i["suggested_action"] for i in issues}
    assert actions.get("cat") == "fill_missing"
    assert actions.get("num") == "review", "a number must not be labelled Unknown"


# --- C22 ordering between columns -------------------------------------------
#
# The opposite shape to C12 and C13. There the rule is the finding and has to be
# exact; here the exceptions are the finding, so the rule has to be established
# on nearly every row before a handful of violations mean anything at all.

def dated(n=300, broken=()):
    import datetime as dt

    rows = []
    for i in range(n):
        ordered = dt.date(2024, 1, 1) + dt.timedelta(days=i % 250)
        shipped = ordered + dt.timedelta(days=(i % 9) + 1)
        if i in broken:
            shipped = ordered - dt.timedelta(days=3)
        rows.append((ordered.isoformat(), shipped.isoformat()))
    return pd.DataFrame(rows, columns=["ordered", "shipped"])


def test_a_ship_date_before_its_order_date_is_reported():
    issues = find(audit(dated(broken=(5, 40, 111))), "C22_ordering_violation")
    assert issues
    assert issues[0]["severity"] == "high"
    assert sorted(issues[0]["row_indices"]) == [5, 40, 111]


def test_a_pair_that_is_always_in_order_is_not_a_finding():
    # Nothing is wrong, so there is nothing to say. A rule with no exceptions is
    # C13's territory, not this check's.
    assert not find(audit(dated()), "C22_ordering_violation")


def test_a_pair_with_no_order_to_it_is_left_alone():
    rng = np.random.default_rng(0)
    df = pd.DataFrame({
        "a": [f"2024-01-{d:02d}" for d in rng.integers(1, 29, 300)],
        "b": [f"2024-01-{d:02d}" for d in rng.integers(1, 29, 300)],
    })
    assert not find(audit(df), "C22_ordering_violation")


def test_too_many_violations_means_there_was_no_rule():
    # A fifth of the rows going the other way is not a rule with exceptions. It
    # is two populations, and calling either one an error would be wrong.
    issues = find(audit(dated(broken=tuple(range(0, 300, 5)))), "C22_ordering_violation")
    assert not issues


def test_a_minimum_above_its_maximum_is_reported():
    rng = np.random.default_rng(1)
    low = rng.uniform(5, 50, 300).round(2)
    high = (low + rng.uniform(1, 30, 300)).round(2)
    low[7], high[7] = high[7], low[7]
    low[90], high[90] = high[90], low[90]
    df = pd.DataFrame({"min_price": low, "max_price": high}).astype(str)
    issues = find(audit(df), "C22_ordering_violation")
    assert issues and sorted(issues[0]["row_indices"]) == [7, 90]


def test_nothing_is_offered_to_fix():
    # Which of the two values is the wrong one is not something the file says.
    issues = find(audit(dated(broken=(5, 40))), "C22_ordering_violation")
    assert issues and issues[0]["suggested_action"] == "review"


# --- C13 on a wide file -------------------------------------------------------

def test_arithmetic_is_still_found_among_two_dozen_columns():
    # The cap used to be ten numeric columns, and a sales export with a dozen
    # measures in it got no arithmetic checked at all. Candidates are now tried
    # against a few complete rows first, which costs three multiplications and
    # rejects almost all of them.
    rng = np.random.default_rng(2)
    n = 400
    qty = rng.integers(1, 10, n)
    price = rng.uniform(2, 60, n).round(2)
    total = (qty * price).round(2)
    data = {"qty": qty, "price": price, "total": total}
    for i in range(22):
        data[f"m{i}"] = rng.uniform(0, 100, n).round(2)
    df = pd.DataFrame(data).astype(str)
    df.loc[df.index[::40], "total"] = ""

    issues = find(audit(df), "C13_arithmetic_relation", "total")
    assert issues and issues[0]["evidence"]["operation"] == "product"
    assert {issues[0]["evidence"]["left"], issues[0]["evidence"]["right"]} == {"qty", "price"}


def test_a_wide_file_with_no_relation_in_it_reports_none():
    rng = np.random.default_rng(3)
    df = pd.DataFrame(
        {f"m{i}": rng.uniform(0, 100, 300).round(2) for i in range(25)}
    ).astype(str)
    assert not find(audit(df), "C13_arithmetic_relation")
