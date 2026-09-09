"""Rows that are not data, at the top and the bottom of the file.

A spreadsheet export opens with a title and a generated-on line, and grows a
totals row at the bottom. Read literally, the first turns the header into
"Sales Report 2023" and "Unnamed: 1", and the second becomes the largest record
in the file. Both are common enough that a tool which cannot handle them cannot
handle exported spreadsheets, which is most of what people have.
"""

import pandas as pd
import pytest

from sift import profile as prof, runner


def audit(csv):
    return runner.audit(runner.load(csv))["issues"]


def rows(n=20):
    return "\n".join(f"x{i},{i},{i * 2}" for i in range(1, n + 1))


# --- the preamble ------------------------------------------------------------

@pytest.mark.parametrize(
    "name,text,columns",
    [
        ("a title and a blank", "Sales Report 2023,,\n\nid,name,v\n1,x,2\n3,y,4\n", ["id", "name", "v"]),
        ("comment lines", "# generated\n# by finance\na,b\n1,2\n3,4\n", ["a", "b"]),
        ("title then generated-on", "Q3,,\nrun 2023-10-01,,\n\nid,name,v\n1,x,2\n", ["id", "name", "v"]),
        ("no preamble at all", "a,b\n1,2\n3,4\n", ["a", "b"]),
        ("a header with one blank name", "a,,b\n1,2,3\n4,5,6\n", ["a", "column_2", "b"]),
    ],
)
def test_the_header_is_found_rather_than_assumed(name, text, columns):
    assert list(prof.load_csv(text).columns) == columns, name


def test_the_preamble_rows_do_not_become_data():
    frame = prof.load_csv("Sales Report 2023,,\n\nid,name,v\n1,x,2\n3,y,4\n")
    assert len(frame) == 2
    assert "Sales Report 2023" not in frame.values


def test_a_file_that_is_all_preamble_still_returns_something():
    # Nothing looks like a header, so the first row is used and nothing is lost.
    frame = prof.load_csv("just a note,,\nanother note,,\n")
    assert len(frame.columns) == 3


# --- the totals row ----------------------------------------------------------

def test_a_labelled_totals_row_is_found():
    issue = [i for i in audit(f"item,a,b\n{rows()}\nTOTAL,210,420\n") if i["check"] == "D5_summary_row"]
    assert issue and issue[0]["evidence"]["auto_apply"] is True
    assert issue[0]["row_indices"] == [20]


def test_an_unlabelled_totals_row_is_found_by_the_arithmetic():
    issue = [i for i in audit(f"item,a,b\n{rows()}\nx99,210,420\n") if i["check"] == "D5_summary_row"]
    assert issue and issue[0]["evidence"]["auto_apply"] is True


def test_one_column_adding_up_by_chance_is_not_enough():
    issue = [i for i in audit(f"item,a,b\n{rows()}\nx99,210,7\n") if i["check"] == "D5_summary_row"]
    assert issue, "a partial match is still worth reporting"
    assert issue[0]["evidence"]["auto_apply"] is False


def test_an_ordinary_last_row_is_left_alone():
    assert not [i for i in audit(f"item,a,b\n{rows()}\n") if i["check"] == "D5_summary_row"]
    assert not [i for i in audit(f"item,a,b\n{rows()}\nx99,999,999\n") if i["check"] == "D5_summary_row"]


def test_a_totals_row_is_found_even_in_a_column_typed_as_an_identifier():
    # Distinct whole numbers classify as an identifier, and a totals row still
    # totals them, so the check reads the values rather than trusting the type.
    issue = [i for i in audit(f"item,a,b\n{rows()}\nTOTAL,210,420\n") if i["check"] == "D5_summary_row"]
    assert issue


# --- times that are not dates ------------------------------------------------

@pytest.mark.parametrize(
    "values,expected",
    [
        ([f"{i % 24:02d}:30:00" for i in range(60)], "categorical"),
        ([f"2023-04-{(i % 28) + 1:02d}" for i in range(60)], "datetime"),
        ([f"2023-04-01 {i % 24:02d}:00:00" for i in range(60)], "datetime"),
    ],
)
def test_a_time_of_day_is_not_a_date(values, expected):
    # pandas reads "14:30:00" as that time today, inventing a date that is not
    # in the file and that changes every day the file is opened.
    assert prof.infer_type(pd.Series(values), len(values)) == expected


# --- a header split over two rows --------------------------------------------
#
# A merged cell in a spreadsheet has no representation in CSV. "Q1" spanning two
# columns comes out as "Q1" and then a blank, with the sub-headings underneath.
# Read as one header, the file has a column named nothing and two named
# "revenue"; read as a header plus a data row, it has a row of text where the
# numbers should be.

def test_a_merged_header_is_joined_into_one_name_per_column():
    frame = prof.load_csv(
        "Region,Q1,,Q2,\n"
        ",revenue,units,revenue,units\n"
        "North,5,2,6,3\n"
        "South,7,1,8,4\n"
    )
    assert list(frame.columns) == [
        "Region", "Q1 revenue", "Q1 units", "Q2 revenue", "Q2 units",
    ]
    assert len(frame) == 2


def test_a_merged_header_is_found_under_a_preamble_too():
    frame = prof.load_csv(
        "Quarterly report\n"
        "generated 2026-09-09\n"
        "\n"
        "Region,Q1,,Q2,\n"
        ",revenue,units,revenue,units\n"
        "North,5,2,6,3\n"
        "South,7,1,8,4\n"
    )
    assert list(frame.columns)[1] == "Q1 revenue"
    assert len(frame) == 2


def test_an_ordinary_header_keeps_its_first_data_row():
    frame = prof.load_csv("a,b,c\nx,y,z\n1,2,3\n")
    assert list(frame.columns) == ["a", "b", "c"]
    assert len(frame) == 2


def test_a_table_of_text_is_not_guessed_at():
    # With no numbers below it, a second row of words cannot be told from data,
    # and inventing a two-row header would silently eat a record.
    frame = prof.load_csv("a,,c\np,q,r\ns,t,u\n")
    assert len(frame) == 2


def test_a_second_row_carrying_numbers_is_data():
    frame = prof.load_csv("a,,c\n1,2,3\n4,5,6\n")
    assert len(frame) == 2


def test_columns_that_would_collide_are_not_joined():
    # Joining has to leave every column with a name of its own, or it has made
    # the file worse than the reading it replaced.
    frame = prof.load_csv("a,,c\nx,x,x\n1,2,3\n")
    assert len(frame) == 2
