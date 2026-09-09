"""The API contract, frozen.

The frontend is built against src/fixtures, so a change to the response shape
that nobody notices here becomes a rendering bug days later. These assert the
shape rather than the values.
"""

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parent.parent / "src" / "fixtures"

ISSUE_KEYS = {
    "id", "check", "scope", "severity", "title", "detail", "column",
    "row_indices", "total_affected", "suggested_action", "evidence",
}
SUMMARY_KEYS = {"high", "medium", "low", "rows_affected", "cv_accuracy", "skipped_checks"}
ACTIONS = {
    "drop_rows", "relabel", "dedupe", "drop_column", "normalize_values", "review", "none",
    "blank_values", "fill_missing", "fill_from_column", "fill_from_formula", "trim",
}


def load(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture(scope="module")
def audits():
    return {n: load(n) for n in ("audit_churn", "audit_reviews", "audit_no_label")}


def test_the_fixtures_exist():
    # They are committed on purpose: the frontend must build without a backend.
    for name in ("profile_churn", "audit_churn", "audit_reviews", "audit_no_label"):
        assert (FIXTURES / f"{name}.json").exists(), f"run scripts/make_fixtures.py ({name})"


def test_profile_response_shape():
    body = load("profile_churn")
    assert set(body) == {"n_rows", "n_cols", "columns", "preview"}
    assert len(body["preview"]) == 20
    for column in body["columns"]:
        assert {"name", "inferred_type", "n_missing", "missing_fraction", "n_unique"} <= set(column)


def test_audit_response_shape(audits):
    for name, body in audits.items():
        assert set(body) == {"issues", "summary"}, name
        assert set(body["summary"]) == SUMMARY_KEYS, name


def test_every_issue_matches_the_documented_shape(audits):
    for name, body in audits.items():
        for issue in body["issues"]:
            assert set(issue) == ISSUE_KEYS, f"{name}: {issue['id']}"
            assert issue["severity"] in {"high", "medium", "low"}
            assert issue["scope"] in {"dataset", "column", "row"}
            assert issue["suggested_action"] in ACTIONS
            assert isinstance(issue["row_indices"], list)
            assert issue["total_affected"] >= len(issue["row_indices"])


def test_row_indices_never_exceed_the_cap(audits):
    from sift import config

    for name, body in audits.items():
        for issue in body["issues"]:
            assert len(issue["row_indices"]) <= config.MAX_ROW_INDICES, name


def test_a_run_without_a_label_says_what_it_skipped():
    summary = load("audit_no_label")["summary"]
    assert summary["cv_accuracy"] is None
    skipped = {s["check"] for s in summary["skipped_checks"]}
    assert {"R1_mislabels", "C10_leakage", "D4_train_test_overlap"} <= skipped
    for entry in summary["skipped_checks"]:
        assert entry["reason"], "a skipped check has to say why"


def test_cv_accuracy_accompanies_every_mislabel_flag(audits):
    # The flags are worthless without it, which is the argument the tool makes.
    for name, body in audits.items():
        for issue in body["issues"]:
            if issue["check"] == "R1_mislabels":
                assert isinstance(issue["evidence"]["cv_accuracy"], float)
                assert isinstance(issue["evidence"]["low_confidence"], bool)
                assert body["summary"]["cv_accuracy"] is not None


def test_fixtures_match_what_the_server_returns_now(churn_loaded):
    # Guards against the fixtures going stale after a change to the checks.
    from sift import runner

    fresh = runner.audit(churn_loaded, label_column="churned", split_column="split")
    stored = load("audit_churn")
    assert [i["id"] for i in fresh["issues"]] == [i["id"] for i in stored["issues"]]
    assert fresh["summary"]["high"] == stored["summary"]["high"]
