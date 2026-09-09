"""C19, C20 and C21, and the words for "missing" that are not English.

Three faults that a hand-written cleaning script deals with in its first twenty
lines and that a generic tool usually cannot see at all: one company written
four ways, characters with no width sitting inside a value, and text that still
has the web page attached to it.

Each has the same shape of risk, which is over-reach. Merging two names is a
claim about the world, so C19 reports and never applies. Removing a character is
a claim about the text, so C20 and C21 only touch what is provably invisible or
provably markup, and both have a test here that they leave ordinary values be.
"""

import pandas as pd
import pytest

from sift import config, formats, profile as prof


def audit(df):
    from sift import runner

    return runner.audit(df)["issues"]


def find(issues, check, column=None):
    out = [i for i in issues if i["check"] == check]
    return [i for i in out if i["column"] == column] if column else out


def padding(n=60):
    """A second column, so that a frame is a table rather than a list."""
    return [str(i) for i in range(n)]


# --- non-English words for "missing" ----------------------------------------

@pytest.mark.parametrize(
    "token",
    ["unbekannt", "inconnu", "desconocido", "sconosciuto", "onbekend",
     "nao informado", "brak danych", "keine angabe", "sin datos",
     chr(0x4E0D) + chr(0x660E), chr(0xBBF8) + chr(0xC0C1)],
)
def test_a_word_for_missing_counts_as_missing_in_any_language(token):
    assert prof.normalise_text(token) in config.MISSING_TOKENS
    assert prof.normalise_text(token) in config.SENTINEL_TOKENS


def test_an_accented_spelling_still_matches():
    # normalise_text strips the accent, so the table only lists the plain form.
    assert prof.normalise_text("Não informado") in config.MISSING_TOKENS


def test_a_german_export_has_its_gaps_counted():
    df = pd.DataFrame({
        "stadt": (["Berlin", "Hamburg", "unbekannt", "Koln"] * 15)[:60],
        "n": padding(),
    })
    reported = find(audit(df), "C1_missingness", "stadt")
    assert reported and reported[0]["total_affected"] == 15


def test_an_ordinary_word_is_not_swept_up():
    # "none" means missing; "nine" does not. The list is a list, not a guess.
    assert prof.normalise_text("nine") not in config.MISSING_TOKENS
    assert prof.normalise_text("nada mas") not in config.MISSING_TOKENS


# --- C19 entity variants ------------------------------------------------------

def test_one_company_written_several_ways_is_reported():
    names = ["Acme Inc", "ACME, Inc.", "Acme Incorporated", "Globex Ltd", "Globex Limited"]
    df = pd.DataFrame({"vendor": (names * 12)[:60], "n": padding()})
    found = find(audit(df), "C19_entity_variants", "vendor")
    assert found
    groups = found[0]["evidence"]["canonical"]
    assert len(groups) == 2
    assert sorted(next(v for v in groups.values() if len(v) == 3)) == [
        "ACME, Inc.", "Acme Inc", "Acme Incorporated",
    ]


def test_it_never_applies_itself():
    # Two names reducing to the same key are not always the same company. The
    # finding is offered; the merge is the user's.
    df = pd.DataFrame({
        "vendor": (["Smith Ltd", "Smith Co", "Jones PLC", "Jones Limited"] * 15)[:60],
        "n": padding(),
    })
    found = find(audit(df), "C19_entity_variants", "vendor")
    assert found and found[0]["evidence"]["auto_apply"] is False


def test_it_leaves_alone_what_c5_already_merges():
    # Case and space are C5's business. If that is the only difference, this
    # check has nothing to add and must not report the same rows twice.
    df = pd.DataFrame({"vendor": (["Acme Inc", "ACME INC", " acme inc "] * 20)[:60], "n": padding()})
    assert not find(audit(df), "C19_entity_variants", "vendor")


def test_it_does_not_group_part_numbers():
    df = pd.DataFrame({"part": [f"AB-{i:04d}" for i in range(60)], "n": padding()})
    assert not find(audit(df), "C19_entity_variants", "part")


def test_two_genuinely_different_names_stay_apart():
    df = pd.DataFrame({
        "vendor": (["Acme Systems", "Beta Holdings", "Cairn Partners"] * 20)[:60],
        "n": padding(),
    })
    assert not find(audit(df), "C19_entity_variants", "vendor")


# --- C20 invisible characters -------------------------------------------------

def test_a_zero_width_space_inside_a_value_is_found():
    dirty = "Lon" + chr(0x200B) + "don"
    df = pd.DataFrame({"city": (["London", dirty, "Leeds"] * 20)[:60], "n": padding()})
    found = find(audit(df), "C20_invisible_characters")
    assert found and found[0]["total_affected"] == 20


def test_a_non_breaking_space_is_found_too():
    df = pd.DataFrame({
        "city": (["London", "New" + chr(0x00A0) + "York", "Leeds"] * 20)[:60],
        "n": padding(),
    })
    assert find(audit(df), "C20_invisible_characters")


def test_an_ordinary_table_reports_nothing():
    df = pd.DataFrame({"city": (["London", "Leeds", "York"] * 20)[:60], "n": padding()})
    assert not find(audit(df), "C20_invisible_characters")


def test_stripping_keeps_the_space_and_drops_the_nothing():
    assert formats.strip_invisible("New" + chr(0x00A0) + "York") == "New York"
    assert formats.strip_invisible("Lon" + chr(0x200B) + "don") == "London"
    assert formats.strip_invisible("plain") == "plain"


# --- C21 markup ---------------------------------------------------------------

def test_html_left_in_a_review_column_is_reported():
    bodies = [
        "Great <b>product</b> and fast delivery every time",
        "Arrived broken &amp; the box was open when it got here",
        "Perfectly ordinary sentence with nothing wrong with it at all",
    ]
    df = pd.DataFrame({"review": (bodies * 20)[:60], "n": padding()})
    found = find(audit(df), "C21_markup", "review")
    assert found and found[0]["total_affected"] == 40
    assert found[0]["suggested_action"] == "strip_markup"


def test_a_comparison_is_not_markup():
    bodies = [
        "The result was a < b in every trial we ran during the study",
        "We measured 3 > 2 on the second and third attempts as well",
        "Nothing here resembles a tag or an entity of any kind at all",
    ]
    df = pd.DataFrame({"note": (bodies * 20)[:60], "n": padding()})
    assert not find(audit(df), "C21_markup", "note")


def test_stripping_leaves_the_words_and_the_spacing_between_them():
    assert formats.strip_markup("Great <b>product</b> &amp; fast") == "Great product & fast"
    assert formats.strip_markup("one<br>two") == "one two"
    assert formats.strip_markup("a < b and 3 > 2") == "a < b and 3 > 2"
    assert formats.strip_markup("AT&T and R&D") == "AT&T and R&D"


def test_an_entity_the_list_does_not_know_is_left_where_it_is():
    # Detection and repair share one list, so nothing is flagged that would not
    # then be removed, and nothing is removed that was not understood.
    assert formats.strip_markup("&someunknownthing;") == "&someunknownthing;"
