"""C11, C12, C13 and C14 - the checks that make the one-click fix worth pressing.

These are held to a stricter standard than the rest of the tool. A check that
fills a cell is writing data the user did not write, so each one has a test that
it fires when the rule is exact and a test that it stays quiet when it is not.
"""

import numpy as np
import pandas as pd
import pytest

from sift import config, profile as prof
from sift.checks import columns as column_checks, relations


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
