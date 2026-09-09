"""Each check is measured against the defects the generator recorded, so a
failure says the check missed known rows rather than that output changed shape."""


def recall(found_rows, planted):
    planted = set(planted)
    return len(set(found_rows) & planted) / len(planted)


def test_c1_flags_the_column_that_was_blanked(churn_issues, churn_truth, by_check):
    found = by_check(churn_issues, "C1_missingness", column=churn_truth["missing_cols"][0])
    assert found and found[0]["severity"] == "medium"


def test_c1_recovers_every_sparse_row(churn_issues, churn_truth, by_check):
    found = by_check(churn_issues, "C1_sparse_rows")
    assert found
    assert recall(found[0]["row_indices"], churn_truth["sparse_row_idx"]) == 1.0


def test_c2_flags_the_constant_column(churn_issues, churn_truth, by_check):
    found = by_check(churn_issues, "C2_constant", column=churn_truth["constant_cols"][0])
    assert found and found[0]["suggested_action"] == "drop_column"


def test_c3_flags_the_id_column_but_not_the_label(churn_issues, churn_truth, by_check):
    flagged = {i["column"] for i in by_check(churn_issues, "C3_id_like")}
    assert churn_truth["id_cols"][0] in flagged
    assert churn_truth["label_column"] not in flagged


def test_c4_flags_the_mixed_type_column(churn_issues, churn_truth, by_check):
    found = by_check(churn_issues, "C4_mixed_types", column=churn_truth["mixed_type_cols"][0])
    assert found
    # The sentinels are the reason it will not parse, so they must be named.
    assert "N/A" in str(found[0]["evidence"]["examples"]) or "none" in str(
        found[0]["evidence"]["examples"]
    )


def test_c5_groups_the_case_and_whitespace_variants(churn_issues, churn_truth, by_check):
    found = by_check(churn_issues, "C5_categorical_inconsistency",
                     column=churn_truth["dirty_cat_cols"][0])
    assert found
    canonical = found[0]["evidence"]["canonical"]
    variants = next(iter(canonical.values()))
    assert {v.strip().lower() for v in variants} == {"premium"}
    assert len(variants) == 4


def test_c5_finds_the_hidden_label_classes(reviews_issues, by_check):
    found = by_check(reviews_issues, "C5_categorical_inconsistency", column="sentiment")
    assert found and len(found[0]["evidence"]["canonical"]) == 3


def test_c6_flags_the_rare_category(churn_issues, by_check):
    found = by_check(churn_issues, "C6_rare_categories", column="plan")
    assert found and "Enterprise" in found[0]["evidence"]["rare"]


def test_c7_recovers_every_planted_outlier(churn_issues, churn_truth, by_check):
    found = by_check(churn_issues, "C7_outliers", column="tenure_months")
    assert found
    assert recall(found[0]["row_indices"], churn_truth["outlier_idx"]) == 1.0


def test_c7_uses_mad_not_standard_deviation():
    # The reason for the design decision: enough extreme values inflate the
    # standard deviation past their own distance from the mean, so a sigma rule
    # stops seeing them. The median absolute deviation does not move.
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(0)
    v = pd.Series(np.concatenate([rng.normal(10, 1, 50), np.full(8, 1000.0)]))

    by_std = ((v - v.mean()).abs() / v.std() > 3).sum()
    mad = (v - v.median()).abs().median()
    by_mad = ((v - v.median()).abs() / (1.4826 * mad) > 5).sum()

    assert by_std == 0, "standard deviation should be masked by its own outliers"
    assert by_mad == 8


def test_c8_recovers_the_future_dates(churn_issues, churn_truth, by_check):
    found = [i for i in by_check(churn_issues, "C8_implausible")
             if i["id"].startswith("future_dates")]
    assert found
    assert recall(found[0]["row_indices"], churn_truth["implausible_idx"]) == 1.0


def test_c9_finds_the_redundant_pair(churn_issues, churn_truth, by_check):
    a, b = churn_truth["redundant_pairs"][0]
    pairs = [set(i["evidence"]["pair"]) for i in by_check(churn_issues, "C9_redundant")]
    assert {a, b} in pairs


def test_d1_recovers_every_duplicate_row(churn_issues, churn_truth, by_check):
    found = by_check(churn_issues, "D1_exact_duplicates")
    assert found
    assert recall(found[0]["row_indices"], churn_truth["exact_dup_idx"]) == 1.0


def test_d3_fires_on_the_reviews_label_only(churn_issues, reviews_issues, by_check):
    assert by_check(reviews_issues, "D3_class_imbalance")
    # Churn is close to balanced, so a warning there would be a false positive.
    assert not by_check(churn_issues, "D3_class_imbalance")


def test_every_issue_matches_the_contract(churn_issues):
    required = {"id", "check", "scope", "severity", "title", "detail", "column",
                "row_indices", "total_affected", "suggested_action", "evidence"}
    for issue in churn_issues:
        assert set(issue) == required
        assert issue["severity"] in {"high", "medium", "low"}
        assert issue["scope"] in {"dataset", "column", "row"}
        assert issue["detail"].endswith(".")


def test_issues_are_ordered_by_severity(churn_issues):
    rank = {"high": 0, "medium": 1, "low": 2}
    order = [rank[i["severity"]] for i in churn_issues]
    assert order == sorted(order)
