"""Dataset-level checks. D1 and D3 here; D2 and D4 need the shared encoder."""

from __future__ import annotations

import pandas as pd

from .. import config, profile as prof
from ..issue import HIGH, LOW, MEDIUM, make_issue, pct


def _exact_duplicates(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    duplicated = df.duplicated(keep=False)
    if not duplicated.any():
        return []
    rows = df.index[duplicated]
    n_groups = int(df[duplicated].groupby(list(df.columns), dropna=False).ngroups)
    extra = len(rows) - n_groups
    return [
        make_issue(
            id="exact_duplicates", check="D1_exact_duplicates", scope="dataset",
            severity=MEDIUM,
            title=f"{len(rows)} rows are exact duplicates",
            detail=(
                f"{len(rows)} rows fall into {n_groups} groups of identical records, "
                f"{extra} of them redundant. Duplicates weight those records more heavily "
                "during training and inflate any score computed over them."
            ),
            row_indices=rows, suggested_action="dedupe",
            evidence={"n_groups": n_groups, "n_redundant": extra},
        )
    ]


def _class_imbalance(df: pd.DataFrame, label_column: str | None) -> list[dict]:
    if not label_column or label_column not in df.columns:
        return []
    labels = prof.present(df[label_column])
    counts = labels.value_counts()
    if len(counts) < 2:
        return []

    smallest, n_smallest = counts.index[-1], int(counts.iloc[-1])
    share = n_smallest / len(labels)
    if share >= config.MIN_CLASS_FRACTION and n_smallest >= config.MIN_CLASS_ROWS:
        return []

    # Below the fold count, stratified cross-validation cannot place a member of
    # the class in every fold, so the label-aware checks quietly drop it.
    severity = MEDIUM if n_smallest < config.CV_FOLDS else LOW
    detail = (
        f"'{smallest}' has {n_smallest} rows, {pct(share)} of the labelled data. "
    )
    detail += (
        f"That is fewer than the {config.CV_FOLDS} cross-validation folds, so the "
        "mislabel and leakage checks will drop this class rather than score it."
        if severity == MEDIUM
        else "A model will learn to ignore it and still look accurate."
    )
    return [
        make_issue(
            id=f"imbalance:{label_column}", check="D3_class_imbalance", scope="dataset",
            severity=severity,
            title=f"Smallest class in '{label_column}' is {pct(share)} of rows",
            detail=detail, column=label_column,
            row_indices=df.index[labels.eq(smallest).reindex(df.index, fill_value=False)],
            suggested_action="review",
            evidence={"counts": {str(k): int(v) for k, v in counts.items()}},
        )
    ]


def _comparison_keys(df: pd.DataFrame, profiles: list[dict]) -> dict[str, pd.Series]:
    # Case and whitespace variants of the same value must count as agreeing, or
    # every row C5 flags would also read as a distinct record here.
    return {
        p["name"]: df[p["name"]].fillna("").astype(str).map(prof.normalise_text)
        for p in profiles
    }


def _column_scales(df: pd.DataFrame, profiles: list[dict]) -> dict[str, float]:
    # Tolerance has to be relative to how much the column varies, not to the
    # size of the value. A month differing by one is the same edit whether the
    # tenure is 3 or 60, but as a share of the value it is 33% or 1.7%.
    scales = {}
    for p in profiles:
        if p["inferred_type"] != prof.NUMERIC:
            continue
        values = prof.as_numeric(df[p["name"]]).dropna()
        if values.empty:
            continue
        spread = float(values.quantile(0.75) - values.quantile(0.25)) or float(values.std() or 0)
        scales[p["name"]] = spread or 1.0
    return scales


def _text_matrices(df: pd.DataFrame, profiles: list[dict]) -> dict:
    """One TF-IDF fit per text column, over the whole column.

    Fitting per candidate bucket would compute inverse document frequency from
    two documents, which makes every term equally rare and the similarity
    meaningless.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.preprocessing import normalize

    out = {}
    for p in profiles:
        if p["inferred_type"] != prof.TEXT:
            continue
        texts = df[p["name"]].fillna("").astype(str)
        if texts.str.strip().eq("").all():
            continue
        try:
            matrix = TfidfVectorizer(ngram_range=config.TFIDF_NGRAM_RANGE).fit_transform(texts)
        except ValueError:
            continue
        out[p["name"]] = normalize(matrix)
    return out


def _fields_close(
    df: pd.DataFrame, col: str, kind: str, a: int, b: int, scales: dict, texts: dict
) -> tuple[bool, str]:
    left, right = df.at[a, col], df.at[b, col]
    if kind == prof.NUMERIC:
        x, y = pd.to_numeric([left, right], errors="coerce")
        if pd.isna(x) or pd.isna(y):
            return False, ""
        gap = abs(x - y)
        if gap <= config.NEAR_DUP_NUMERIC_TOLERANCE * scales.get(col, 1.0):
            return True, f"'{col}' differs slightly"
        return False, ""
    if kind == prof.TEXT:
        matrix = texts.get(col)
        if matrix is None:
            return False, ""
        pos = df.index.get_indexer([a, b])
        sim = float((matrix[pos[0]] @ matrix[pos[1]].T).toarray()[0, 0])
        if sim >= config.NEAR_DUP_THRESHOLD:
            return True, f"'{col}' is {sim:.2f} similar"
        return False, ""
    return prof.normalise_text(str(left)) == prof.normalise_text(str(right)), f"'{col}' respelled"


def _candidate_pairs(
    df: pd.DataFrame, profiles: list[dict], compare_cols: list[str]
) -> dict[tuple[int, int], str]:
    """Pairs agreeing on every compared column but one.

    Hashing each leave-one-out view keeps this linear in the row count. The
    quadratic step only ever runs inside a bucket of rows already known to agree
    on everything else.
    """
    keys = _comparison_keys(df, profiles)
    kinds = {p["name"]: p["inferred_type"] for p in profiles}
    scales = _column_scales(df, profiles)
    texts = _text_matrices(df, profiles)
    found: dict[tuple[int, int], str] = {}

    for dropped in compare_cols:
        others = [c for c in compare_cols if c != dropped]
        if not others:
            continue
        signature = pd.util.hash_pandas_object(
            pd.DataFrame({c: keys[c] for c in others}), index=False
        )
        buckets = pd.Series(df.index, index=signature.to_numpy()).groupby(level=0).apply(list)
        for members in buckets:
            if len(members) < 2 or len(members) > config.NEAR_DUP_MAX_GROUP:
                continue
            for i, a in enumerate(members):
                for b in members[i + 1:]:
                    pair = (min(a, b), max(a, b))
                    if pair in found:
                        continue
                    ok, why = _fields_close(df, dropped, kinds[dropped], a, b, scales, texts)
                    if ok:
                        found[pair] = why
    return found


def _near_duplicates(df: pd.DataFrame, profiles: list[dict], split_column: str | None) -> tuple[list[dict], list[dict]]:
    if len(df) < 2:
        return [], []
    if len(df) > config.NEAR_DUP_MAX_ROWS:
        return [
            make_issue(
                id="near_duplicates_skipped", check="D2_near_duplicates", scope="dataset",
                severity=LOW,
                title=f"Near-duplicate detection skipped above {config.NEAR_DUP_MAX_ROWS:,} rows",
                detail=(
                    f"This file has {len(df):,} rows. Past {config.NEAR_DUP_MAX_ROWS:,} the "
                    "pairwise step needs approximate nearest neighbours rather than a full "
                    "comparison. Exact duplicates were still checked."
                ),
                suggested_action="none",
            )
        ], [{"check": "D2_near_duplicates", "reason": "row count above the cap"}]

    compare_cols = [c for c in df.columns if c != split_column]
    pairs = _candidate_pairs(df, profiles, compare_cols)
    exact = set(df.index[df.duplicated(subset=compare_cols, keep=False)])
    inexact = {p: why for p, why in pairs.items() if not (p[0] in exact and p[1] in exact)}
    if not inexact:
        return [], []

    rows = sorted({r for pair in inexact for r in pair})
    reasons = pd.Series(list(inexact.values())).value_counts().head(3)
    return [
        make_issue(
            id="near_duplicates", check="D2_near_duplicates", scope="dataset", severity=MEDIUM,
            title=f"{len(inexact)} near-duplicate row pairs",
            detail=(
                f"{len(inexact)} pairs of rows agree on every field but one, covering "
                f"{len(rows)} rows. Most commonly {reasons.index[0]}. Near-copies usually come "
                "from a re-import or a partial edit, and they weight the same record twice."
            ),
            row_indices=rows, suggested_action="dedupe",
            evidence={
                "n_pairs": len(inexact),
                "pairs": [
                    {"a": int(a), "b": int(b), "differs": why}
                    for (a, b), why in list(inexact.items())[:50]
                ],
            },
        )
    ], []


def _train_test_overlap(
    df: pd.DataFrame, profiles: list[dict], split_column: str | None
) -> tuple[list[dict], list[dict]]:
    if not split_column or split_column not in df.columns:
        return [], [{"check": "D4_train_test_overlap", "reason": "no split column was chosen"}]

    split = df[split_column].fillna("").astype(str)
    if split.nunique() < 2:
        return [], [{"check": "D4_train_test_overlap",
                     "reason": f"'{split_column}' has fewer than two values"}]

    feature_cols = [c for c in df.columns if c != split_column]
    # Hashing the feature columns turns "is this row on both sides" into one
    # groupby instead of comparing every row against every other row.
    key = pd.util.hash_pandas_object(df[feature_cols].astype(str), index=False)
    sides = pd.DataFrame({"key": key.to_numpy(), "split": split.to_numpy()}, index=df.index)
    exact_rows = sides.index[sides["key"].map(sides.groupby("key")["split"].nunique()) > 1]

    near_rows: set = set()
    if len(df) <= config.NEAR_DUP_MAX_ROWS:
        for a, b in _candidate_pairs(df, profiles, feature_cols):
            if split.at[a] != split.at[b]:
                near_rows.update((a, b))

    rows = sorted(set(exact_rows) | near_rows)
    if not rows:
        return [], []

    only_near = len(near_rows - set(exact_rows))
    detail = f"{len(exact_rows)} rows appear identically on both sides of '{split_column}'"
    if only_near:
        detail += f", and {only_near} more are near-identical across it"
    detail += (
        ". Anything measured on this split is measuring memorisation. This is the failure "
        "that produces a high validation score with nothing in the training curve to warn "
        "you, so it is worth fixing before anything else on this list."
    )
    return [
        make_issue(
            id="train_test_overlap", check="D4_train_test_overlap", scope="dataset",
            severity=HIGH,
            title=f"{len(rows)} rows appear on both sides of '{split_column}'",
            detail=detail, column=split_column, row_indices=rows,
            suggested_action="drop_rows",
            evidence={"n_exact": int(len(exact_rows)), "n_near_only": int(only_near)},
        )
    ], []


def run(
    df: pd.DataFrame,
    profiles: list[dict],
    label_column: str | None = None,
    split_column: str | None = None,
) -> tuple[list[dict], list[dict]]:
    near, skip_near = _near_duplicates(df, profiles, split_column)
    overlap, skip_overlap = _train_test_overlap(df, profiles, split_column)
    return (
        [*_exact_duplicates(df), *_class_imbalance(df, label_column), *near, *overlap],
        [*skip_near, *skip_overlap],
    )
