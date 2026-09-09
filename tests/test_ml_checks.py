"""C10, R1, D2 and D4 - the checks that fit a model or compare rows."""

import numpy as np
import pandas as pd
import pytest

from sift import config, encode, profile as prof
from sift.checks import rows as rows_check


def flagged_rows(issues, check):
    return {r for i in issues if i["check"] == check for r in i["row_indices"]}


def recall(found, planted):
    return len(set(found) & set(planted)) / len(planted)


def test_c10_flags_the_leaked_column(churn_issues, churn_truth, by_check):
    found = by_check(churn_issues, "C10_leakage")
    assert [i["column"] for i in found] == churn_truth["leaked_cols"]
    assert found[0]["severity"] == "high"
    assert found[0]["evidence"]["accuracy"] > config.LEAKAGE_ACCURACY


def test_c10_ignores_a_merely_correlated_column(reviews_issues, by_check):
    # rating tracks sentiment closely but is not derived from it. Flagging it
    # would make the check useless on any dataset with a strong feature.
    assert "rating" not in {i["column"] for i in by_check(reviews_issues, "C10_leakage")}


def test_r1_recovers_the_flipped_labels(churn_issues, churn_truth):
    found = flagged_rows(churn_issues, "R1_mislabels")
    assert recall(found, churn_truth["mislabelled_idx"]) >= 0.75
    assert not found - set(churn_truth["mislabelled_idx"])


def test_r1_reports_the_accuracy_of_the_model_that_produced_it(churn_loaded):
    from sift import runner

    summary = runner.audit(churn_loaded, "churned", "split")["summary"]
    assert 0.0 <= summary["cv_accuracy"] <= 1.0


def test_r1_needs_a_label(churn_loaded):
    profiles = prof.profile_frame(churn_loaded)
    out = rows_check.run(churn_loaded, encode.build(churn_loaded, profiles), None)
    assert out["issues"] == [] and out["cv_accuracy"] is None
    assert "no label" in out["skipped"][0]["reason"]


def test_r1_skips_a_frame_too_small_to_cross_validate(churn_loaded):
    small = churn_loaded.head(20)
    profiles = prof.profile_frame(small)
    out = rows_check.run(small, encode.build(small, profiles), "churned")
    assert out["issues"] == []
    assert str(config.MISLABEL_MIN_ROWS) in out["skipped"][0]["reason"]


def test_r1_drops_classes_below_the_fold_count_and_says_so(churn_loaded):
    df = churn_loaded.copy()
    # Three rows of a third class. Stratified 5-fold cannot split them, and the
    # failure is silent unless the check removes them deliberately.
    df.loc[df.index[:3], "churned"] = "2"
    out = rows_check.run(df, encode.build(df, prof.profile_frame(df), "churned"), "churned")
    assert out["dropped_classes"] == {"2": 3}
    assert "'2' (3 rows)" in out["issues"][0]["detail"]


def test_r1_marks_its_flags_low_confidence_when_the_model_is_weak(churn_loaded, monkeypatch):
    monkeypatch.setattr(config, "WEAK_MODEL_ACCURACY", 0.999)
    profiles = prof.profile_frame(churn_loaded)
    out = rows_check.run(churn_loaded, encode.build(churn_loaded, profiles, "churned"), "churned")
    issue = out["issues"][0]
    assert issue["evidence"]["low_confidence"] is True
    assert issue["severity"] == "medium"
    assert "low confidence" in issue["detail"]


def test_d2_recovers_the_near_duplicates_without_false_pairs(churn_issues, churn_truth):
    found = flagged_rows(churn_issues, "D2_near_duplicates")
    assert recall(found, churn_truth["near_dup_idx"]) == 1.0
    assert not found - set(churn_truth["near_dup_idx"])


def test_d2_does_not_use_cosine_over_the_encoded_matrix(churn_loaded):
    # Why the check compares fields instead: on mostly one-hot tabular data,
    # unrelated rows already sit around 0.5 cosine, so the coincidental tail
    # swamps the real pairs at any threshold.
    profiles = prof.profile_frame(churn_loaded)
    X = encode.build(churn_loaded, profiles, "churned", "split").X
    V = encode.l2_normalise(X)
    rng = np.random.default_rng(0)
    a, b = rng.integers(0, len(V), 2000), rng.integers(0, len(V), 2000)
    ok = a != b
    sims = np.einsum("ij,ij->i", V[a[ok]], V[b[ok]])
    assert np.percentile(sims, 99) > 0.9


def test_d4_recovers_the_contaminated_rows(churn_issues, churn_truth):
    found = flagged_rows(churn_issues, "D4_train_test_overlap")
    assert recall(found, churn_truth["overlap_idx"]) == 1.0
    assert not found - set(churn_truth["overlap_idx"])


def test_d4_is_always_high_severity(churn_issues, by_check):
    assert by_check(churn_issues, "D4_train_test_overlap")[0]["severity"] == "high"


def test_d4_needs_a_split_column(churn_loaded):
    from sift.checks import dataset

    _, skipped = dataset.run(churn_loaded, prof.profile_frame(churn_loaded), "churned", None)
    assert any("no split column" in s["reason"] for s in skipped)


def test_d2_explains_itself_instead_of_running_above_the_cap(churn_loaded, monkeypatch):
    monkeypatch.setattr(config, "NEAR_DUP_MAX_ROWS", 10)
    from sift.checks import dataset

    issues, skipped = dataset.run(churn_loaded, prof.profile_frame(churn_loaded), "churned", "split")
    skip_issue = [i for i in issues if i["id"] == "near_duplicates_skipped"]
    assert skip_issue and "approximate nearest neighbours" in skip_issue[0]["detail"]
    assert any(s["check"] == "D2_near_duplicates" for s in skipped)


def test_svd_is_capped_below_the_rank_of_the_matrix():
    # A narrow text column can have a vocabulary smaller than the component
    # count, and asking for more components than rank returns noise.
    assert encode._svd_components(n_features=10, n_samples=1000) == 9
    assert encode._svd_components(n_features=5000, n_samples=1000) == 128


def test_encoding_drops_identifiers_and_constants(churn_loaded):
    profiles = prof.profile_frame(churn_loaded)
    used = encode.build(churn_loaded, profiles, "churned", "split").columns_used
    assert "customer_id" not in used and "region" not in used
    assert "churned" not in used and "split" not in used
