import pandas as pd

from sift import profile as P


def test_types_inferred_on_the_churn_columns(churn_loaded):
    expected = {
        "customer_id": P.ID_LIKE,
        "signup_date": P.DATETIME,
        "region": P.CONSTANT,
        "plan": P.CATEGORICAL,
        "tenure_months": P.NUMERIC,
        "monthly_charges": P.NUMERIC,
        "email": P.ID_LIKE,
        "churned": P.BOOLEAN,
    }
    got = P.types_by_column(P.profile_frame(churn_loaded))
    assert {k: got[k] for k in expected} == expected


def test_free_text_is_not_mistaken_for_an_identifier(reviews_loaded):
    # Review bodies are near-unique, so uniqueness alone would call them ids.
    types = P.types_by_column(P.profile_frame(reviews_loaded))
    assert types["review_body"] == P.TEXT
    assert types["review_id"] == P.ID_LIKE


def test_sentinel_strings_count_as_missing(churn_loaded):
    profiles = {p["name"]: p for p in P.profile_frame(churn_loaded)}
    tokens = profiles["discount_pct"]["missing_tokens"]
    assert {"n/a", "none", "unknown"} <= set(tokens)


def test_integers_are_not_read_as_dates():
    s = pd.Series(["20240101", "19991231", "20200615", "20211102"])
    assert P.infer_type(s, len(s)) != P.DATETIME


def test_uniqueness_is_measured_over_present_values():
    # Three quarters blank, distinct wherever filled. Still an identifier.
    s = pd.Series(["a1", "", "", "", "b2", "", "", "", "c3", "", "", ""])
    assert P.infer_type(s, len(s)) == P.ID_LIKE


def test_continuous_measurements_are_not_identifiers():
    # Distinct on every row, like an id, but the fractional parts say measurement.
    s = pd.Series([f"{v / 7:.3f}" for v in range(1, 60)])
    assert P.infer_type(s, len(s)) == P.NUMERIC


def test_distinct_whole_numbers_are_identifiers():
    s = pd.Series([str(v) for v in range(1000, 1060)])
    assert P.infer_type(s, len(s)) == P.ID_LIKE


def test_tsv_is_detected_from_the_header():
    df = P.load_csv("a\tb\tc\n1\t2\t3\n")
    assert list(df.columns) == ["a", "b", "c"]
