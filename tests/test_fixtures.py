"""The generator is what every later check is measured against, so its ground
truth has to be verifiably true before anything depends on it."""

import pandas as pd

from scripts.make_dirty import make_churn


def test_generation_is_reproducible():
    a, _ = make_churn()
    b, _ = make_churn()
    pd.testing.assert_frame_equal(a, b)


def test_defect_index_sets_are_disjoint(churn_truth):
    # Overlapping defects would make a recall figure ambiguous: a row flagged by
    # the outlier check would also count as a recovered mislabel.
    keys = ["mislabelled_idx", "outlier_idx", "sparse_row_idx", "implausible_idx"]
    seen = set()
    for key in keys:
        idx = set(churn_truth[key])
        assert not (idx & seen), f"{key} overlaps an earlier defect set"
        seen |= idx


def test_mislabelled_rows_disagree_with_the_true_outcome(churn_df, churn_truth):
    # cancellation_reason is written from the real outcome, so on a row whose
    # label was flipped the two must disagree. This is the signal R1 recovers.
    rows = churn_df.loc[churn_truth["mislabelled_idx"]]
    really_churned = rows["cancellation_reason"].fillna("").ne("")
    assert (really_churned != rows["churned"].astype(bool)).all()


def test_unflipped_rows_agree_with_the_true_outcome(churn_df, churn_truth):
    base = churn_df.iloc[: len(churn_df) - 75]
    clean = base.drop(index=churn_truth["mislabelled_idx"])
    really_churned = clean["cancellation_reason"].fillna("").ne("")
    assert (really_churned == clean["churned"].astype(bool)).all()


def test_exact_duplicates_are_present(churn_df, churn_truth):
    dup = churn_df.loc[churn_truth["exact_dup_idx"]]
    assert dup.duplicated(keep=False).sum() == len(churn_truth["exact_dup_idx"])


def test_overlap_rows_sit_on_both_sides_of_the_split(churn_df, churn_truth):
    feature_cols = [c for c in churn_df.columns if c != "split"]
    rows = churn_df.loc[churn_truth["overlap_idx"]]
    key = rows[feature_cols].astype(str).agg("|".join, axis=1)
    assert rows.groupby(key)["split"].nunique().eq(2).all()


def test_outliers_sit_far_outside_the_column(churn_df, churn_truth):
    col = churn_df["tenure_months"]
    flagged = col.loc[churn_truth["outlier_idx"]]
    assert flagged.min() > col.median() * 20


def test_declared_column_properties_hold(churn_df, churn_truth):
    assert churn_df[churn_truth["constant_cols"][0]].nunique() == 1
    assert churn_df[churn_truth["id_cols"][0]].nunique() / len(churn_df) > 0.95
    assert churn_df[churn_truth["missing_cols"][0]].isna().mean() > 0.30
    a, b = churn_truth["redundant_pairs"][0]
    assert churn_df[[a, b]].dropna().corr().iloc[0, 1] > 0.98


def test_plan_has_case_and_whitespace_variants(churn_df):
    raw = set(churn_df["plan"].dropna().unique())
    normalised = {v.strip().lower() for v in raw}
    assert len(raw) > len(normalised)


def test_discount_column_mixes_numbers_and_strings(churn_df, churn_truth):
    col = churn_df[churn_truth["mixed_type_cols"][0]].dropna()
    numeric = pd.to_numeric(col, errors="coerce").notna()
    assert numeric.mean() > 0.02 and (~numeric).mean() > 0.02


def test_reviews_label_has_hidden_extra_classes(reviews_df, reviews_truth):
    raw = reviews_df[reviews_truth["label_column"]].unique()
    normalised = {v.strip().lower() for v in raw}
    assert len(raw) > len(normalised) == 3


def test_reviews_bodies_are_almost_all_distinct(reviews_df):
    # Accidental collisions would drown the planted near-duplicates in noise.
    assert reviews_df["review_body"].nunique() / len(reviews_df) > 0.98


def test_reviews_near_duplicates_are_edits_not_copies(reviews_df, reviews_truth):
    n0 = len(reviews_df) - 25
    sources = [i for i in reviews_truth["near_dup_idx"] if i < n0]
    edited = sum(
        reviews_df.at[s, "review_body"] != reviews_df.at[n0 + k, "review_body"]
        for k, s in enumerate(sources)
    )
    assert edited == len(sources)


def test_sentinel_strings_survive_a_csv_round_trip(churn_df):
    # pandas treats "N/A" as missing by default, which would erase exactly the
    # values C4 and C5 exist to find. The audit endpoint has to read with
    # keep_default_na=False and decide for itself what counts as missing.
    import io

    buf = io.StringIO()
    churn_df.to_csv(buf, index=False)

    default = pd.read_csv(io.StringIO(buf.getvalue()))
    preserved = pd.read_csv(io.StringIO(buf.getvalue()), keep_default_na=False)

    def sentinels(frame):
        col = frame["discount_pct"]
        return (pd.to_numeric(col, errors="coerce").isna() & col.notna()).sum()

    assert sentinels(default) < sentinels(preserved)
    assert "N/A" in set(preserved["discount_pct"].unique())
