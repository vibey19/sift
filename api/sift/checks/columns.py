"""Column-level checks C1 to C9. Pure pandas, no model fitting."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.tree import DecisionTreeClassifier

from .. import config, formats, profile as prof
from ..issue import HIGH, LOW, MEDIUM, make_issue, pct


def _missingness(df: pd.DataFrame, profiles: list[dict]) -> list[dict]:
    issues = []
    for p in profiles:
        frac = p["missing_fraction"]
        if frac <= config.MISSING_WARN:
            continue
        col = p["name"]
        rows = df.index[prof.missing_mask(df[col])]
        severity = MEDIUM if frac > config.MISSING_HIGH else LOW
        spellings = ", ".join(f"'{k}'" for k in p["missing_tokens"]) or None
        detail = (
            f"{p['n_missing']} of {len(df)} rows have no value for '{col}'. "
            + (
                "Rows will be dropped or imputed by most models, and at this share "
                "that changes what the model learns."
                if severity == MEDIUM
                else "Worth knowing before you impute."
            )
        )
        if spellings:
            detail += f" The blanks are written {spellings} as well as empty cells."
        issues.append(
            make_issue(
                id=f"missing:{col}",
                check="C1_missingness",
                scope="column",
                severity=severity,
                title=f"{pct(frac)} of rows missing in '{col}'",
                detail=detail,
                column=col,
                row_indices=rows,
                # A gap in a category is filled with a label rather than left
                # blank, because "" means something different to every tool that
                # reads the file next.
                suggested_action=(
                    "fill_missing"
                    if p["inferred_type"] in (prof.CATEGORICAL, prof.BOOLEAN)
                    else "review"
                ),
                evidence={
                    "missing_fraction": frac,
                    "spellings": p["missing_tokens"],
                    "fill_with": "Unknown",
                },
            )
        )
    return issues


def _sentinel_values(df: pd.DataFrame, profiles: list[dict]) -> list[dict]:
    """Values that mean "missing" but were written as words.

    A column of numbers with ERROR in it does not load as numbers, and a
    spreadsheet that writes UNKNOWN is not distinguishing that from an empty
    cell. The distinction matters only if the marker is a real category, which
    is why a column made mostly of one marker is left alone: at that point it is
    a value, not an absence.
    """
    issues = []
    for p in profiles:
        col = p["name"]
        values = df[col].fillna("")
        hits = values.map(lambda v: prof.normalise_text(v) in config.SENTINEL_TOKENS)
        total = int(hits.sum())
        if total < config.SENTINEL_MIN_COUNT:
            continue
        if len(df) and total / len(df) > config.SENTINEL_MAX_SHARE:
            continue

        counts = values[hits].value_counts()
        forms = [str(f) for f in counts.index[:10]]
        kind = p["inferred_type"]
        consequence = (
            f"Left in place the column will not load as {kind}"
            if kind in (prof.NUMERIC, prof.DATETIME)
            else "Left in place they read as a category rather than as an absence"
        )
        share = total / len(df) if len(df) else 0.0
        modal = str(values.value_counts().index[0]) if len(values) else ""
        automatic = (
            share <= config.SENTINEL_AUTO_MAX_SHARE
            and prof.normalise_text(modal) not in config.SENTINEL_TOKENS
        )
        if not automatic:
            consequence += (
                f". At {total} of {len(df)} rows this is too much of the column to blank "
                "without asking: a marker that common is often a real answer rather than a "
                "missing one, so this one is left for you"
            )

        issues.append(
            make_issue(
                id=f"sentinel:{col}",
                check="C11_sentinel_values",
                scope="column",
                severity=MEDIUM,
                title=f"'{col}' writes missing values as {', '.join(repr(f) for f in forms[:3])}",
                detail=(
                    f"{total} cells in '{col}' hold a word meaning no value rather than a value. "
                    f"{consequence}, and every tool downstream treats them differently. "
                    "Blanking them makes the gap explicit."
                ),
                column=col,
                row_indices=df.index[hits],
                suggested_action="blank_values",
                evidence={"forms": forms, "count": total, "auto_apply": automatic},
            )
        )
    return issues


def _untrimmed(df: pd.DataFrame, profiles: list[dict]) -> list[dict]:
    """Cells with space around them.

    Invisible on screen and fatal to a join, a groupby or a numeric cast. C5
    catches this for categories it can group; this catches it everywhere else,
    including in columns that would otherwise parse as numbers.
    """
    affected: dict[str, int] = {}
    rows: set = set()
    for p in profiles:
        col = p["name"]
        values = df[col].fillna("")
        ragged = values.ne(values.str.strip())
        count = int(ragged.sum())
        if count:
            affected[col] = count
            rows.update(df.index[ragged])
    if not affected:
        return []

    worst = sorted(affected.items(), key=lambda kv: -kv[1])
    named = ", ".join(f"'{c}'" for c, _ in worst[:3])
    return [
        make_issue(
            id="untrimmed",
            check="C14_untrimmed",
            scope="dataset",
            severity=LOW,
            title=f"{sum(affected.values())} cells have space around them",
            detail=(
                f"Padding appears in {len(affected)} columns, most of it in {named}. "
                "Whitespace is invisible on screen and still breaks a join, a grouping "
                "or a numeric cast."
            ),
            row_indices=sorted(rows),
            suggested_action="trim",
            evidence={"columns": dict(worst[:10])},
        )
    ]


def _sparse_rows(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    missing = pd.concat([prof.missing_mask(df[c]) for c in df.columns], axis=1)
    share = missing.mean(axis=1)
    rows = df.index[share > config.SPARSE_ROW_FRACTION]
    if len(rows) == 0:
        return []
    return [
        make_issue(
            id="sparse_rows",
            check="C1_sparse_rows",
            scope="row",
            severity=MEDIUM,
            title=f"{len(rows)} rows are more than half empty",
            detail=(
                f"{len(rows)} rows have no value in over half their columns. Rows this "
                "thin usually come from a broken import rather than genuine gaps."
            ),
            row_indices=rows,
            suggested_action="drop_rows",
        )
    ]


def _constant(df: pd.DataFrame, profiles: list[dict]) -> list[dict]:
    issues = []
    for p in profiles:
        col = p["name"]
        values = prof.present(df[col])
        if values.empty:
            # A column with nothing in it at all. Reported here rather than
            # skipped, because an empty column is the clearest case of the thing
            # this check exists to find.
            issues.append(
                make_issue(
                    id=f"constant:{col}", check="C2_constant", scope="column",
                    severity=LOW,
                    title=f"'{col}' is empty",
                    detail=(
                        f"Not one of the {len(df)} rows has a value for '{col}'. An empty "
                        "column carries nothing and only makes the file wider."
                    ),
                    column=col, total_affected=len(df), suggested_action="drop_column",
                    evidence={"top_value_share": 1.0, "empty": True},
                )
            )
            continue
        top_share = float(values.value_counts(normalize=True).iloc[0])
        if p["inferred_type"] == prof.CONSTANT:
            title = f"'{col}' has the same value in every row"
            detail = (
                f"Every row reads '{values.iloc[0]}'. A column with no variation "
                "cannot carry information and only adds width to the model."
            )
        elif top_share > config.NEAR_CONSTANT_FRACTION:
            title = f"'{col}' is {pct(top_share)} one value"
            detail = (
                f"'{values.value_counts().index[0]}' accounts for {pct(top_share)} of "
                "the column. The remaining rows are too few for a model to learn from."
            )
        else:
            continue
        issues.append(
            make_issue(
                id=f"constant:{col}", check="C2_constant", scope="column",
                severity=LOW, title=title, detail=detail, column=col,
                total_affected=len(df), suggested_action="drop_column",
                evidence={"top_value_share": top_share},
            )
        )
    return issues


def _id_like(profiles: list[dict], label_column: str | None) -> list[dict]:
    issues = []
    for p in profiles:
        col = p["name"]
        if p["inferred_type"] != prof.ID_LIKE or col == label_column:
            continue
        issues.append(
            make_issue(
                id=f"id_column:{col}", check="C3_id_like", scope="column",
                severity=MEDIUM,
                title=f"'{col}' looks like an identifier",
                detail=(
                    f"'{col}' takes {p['n_unique']} distinct values across the "
                    f"{p['n_present']} rows it is filled on. Left in the feature set a "
                    "model can memorise it, which "
                    "scores well in validation and predicts nothing on new rows."
                ),
                column=col, total_affected=p["n_unique"],
                suggested_action="drop_column",
                evidence={"n_unique": p["n_unique"]},
            )
        )
    return issues


def _mixed_types(df: pd.DataFrame, profiles: list[dict]) -> list[dict]:
    issues = []
    for p in profiles:
        col = p["name"]
        if p["inferred_type"] in (prof.TEXT, prof.DATETIME, prof.CONSTANT):
            continue
        values = prof.non_empty(df[col])
        if values.empty:
            continue
        numeric = pd.to_numeric(values.str.replace(",", "", regex=False), errors="coerce")
        num_share = float(numeric.notna().mean())
        str_share = 1.0 - num_share
        if min(num_share, str_share) < config.MIXED_TYPE_MIN_SHARE:
            continue
        offenders = values[numeric.isna()]
        # Words meaning "missing" are C11's finding. Reporting them here as well
        # gives the user the same cells twice under two different names.
        offenders = offenders[~prof.is_sentinel(offenders)]
        if len(offenders) / len(values) < config.MIXED_TYPE_MIN_SHARE:
            continue
        top = offenders.value_counts().head(5)
        sentinel = all(prof.normalise_text(v) in config.MISSING_TOKENS for v in top.index)
        detail = (
            f"{len(offenders)} of {len(values)} filled cells in '{col}' are not numbers, "
            f"the rest are. The non-numeric values are {', '.join(repr(v) for v in top.index[:3])}."
        )
        detail += (
            " These are missing-value markers, so the column will not parse as numeric "
            "until they are blanked."
            if sentinel
            else " Mixed types like this silently become a categorical column."
        )
        issues.append(
            make_issue(
                id=f"mixed_types:{col}", check="C4_mixed_types", scope="column",
                severity=MEDIUM,
                title=f"'{col}' mixes numbers and text",
                detail=detail, column=col, row_indices=offenders.index,
                suggested_action="review",
                evidence={"numeric_share": num_share,
                          "examples": {str(k): int(v) for k, v in top.items()}},
            )
        )
    return issues


def _categorical_inconsistency(df: pd.DataFrame, profiles: list[dict]) -> list[dict]:
    issues = []
    for p in profiles:
        col = p["name"]
        if p["inferred_type"] not in (prof.CATEGORICAL, prof.BOOLEAN):
            continue
        values = prof.present(df[col])
        if values.empty:
            continue
        # A column of Y, yes, TRUE, 1 belongs to C17, which knows the spellings
        # mean two things and writes them one way. Left to this check as well,
        # both fire, and whichever runs second wins: C17 settles on "false" and
        # then this merges it back into "FALSE" because that was more common in
        # the original column.
        if float(values.map(formats.parse_boolean).notna().mean()) >= config.BOOLEAN_MIN_SHARE:
            continue
        groups: dict[str, set] = {}
        for raw in values.unique():
            groups.setdefault(prof.normalise_text(raw), set()).add(raw)
        collisions = {k: v for k, v in groups.items() if len(v) > 1}
        if not collisions:
            continue

        counts = values.value_counts()
        safe, contested, rows = {}, {}, []
        for key, raws in collisions.items():
            canonical = max(raws, key=lambda r: counts.get(r, 0))
            top = int(counts.get(canonical, 0)) or 1
            mergeable, disputed = set(), set()

            for raw in raws - {canonical}:
                # Padding is never meaningful.
                if str(raw).strip() == str(canonical).strip():
                    mergeable.add(raw)
                    continue
                # Case can only be carrying meaning in something code-shaped.
                text = str(raw).strip()
                code_shaped = (not any(c.isspace() for c in text)) and (
                    any(c.isdigit() for c in text) or len(text) <= config.CATEGORY_CODE_MAX_LENGTH
                )
                rare = int(counts.get(raw, 0)) / top <= config.CATEGORY_MERGE_MAX_VARIANT_RATIO
                (mergeable if rare or not code_shaped else disputed).add(raw)

            if mergeable:
                safe[canonical] = sorted({canonical, *mergeable})
                rows.extend(
                    df.index[values.isin(mergeable).reindex(df.index, fill_value=False)]
                )
            if disputed:
                contested[canonical] = sorted({canonical, *disputed})

        example = next(iter({**safe, **contested}.items()))
        detail = (
            f"{', '.join(repr(v) for v in example[1])} are the same value written differently, "
            "and every model will treat them as separate categories. "
        )
        if contested:
            balanced = next(iter(contested.items()))
            detail += (
                f"{len(contested)} of these are left alone: "
                f"{', '.join(repr(v) for v in balanced[1])} appear about as often as each other, "
                "and a spelling used that consistently is more likely to be a distinction than "
                "a slip. Merging them would destroy it, so that is your call rather than a "
                "one-click fix."
            )
        else:
            detail += f"{len(rows)} rows use a non-canonical spelling."

        issues.append(
            make_issue(
                id=f"inconsistent:{col}", check="C5_categorical_inconsistency",
                scope="column", severity=MEDIUM,
                title=f"'{col}' has {len(collisions)} value spelled more than one way"
                if len(collisions) == 1
                else f"'{col}' has {len(collisions)} values spelled more than one way",
                detail=detail,
                column=col, row_indices=rows, suggested_action="normalize_values",
                evidence={
                    "canonical": safe,
                    "contested": contested,
                    "auto_apply": bool(safe),
                },
            )
        )
    return issues


def _rare_categories(df: pd.DataFrame, profiles: list[dict]) -> list[dict]:
    issues = []
    for p in profiles:
        col = p["name"]
        if p["inferred_type"] != prof.CATEGORICAL:
            continue
        values = prof.present(df[col])
        counts = values.value_counts()
        rare = counts[counts < config.RARE_CATEGORY_MIN]
        if rare.empty:
            continue
        rows = df.index[values.isin(rare.index).reindex(df.index, fill_value=False)]
        issues.append(
            make_issue(
                id=f"rare_categories:{col}", check="C6_rare_categories", scope="column",
                severity=LOW,
                title=f"'{col}' has {len(rare)} "
                f"{'category' if len(rare) == 1 else 'categories'} with under "
                f"{config.RARE_CATEGORY_MIN} rows",
                detail=(
                    f"{', '.join(repr(v) for v in rare.index[:3])} appear "
                    f"{'once' if rare.iloc[0] == 1 else f'{int(rare.iloc[0])} times'} or so. "
                    "Categories this thin cannot be learned and will not survive a split."
                ),
                column=col, row_indices=rows, suggested_action="review",
                evidence={"rare": {str(k): int(v) for k, v in rare.items()}},
            )
        )
    return issues


def _outliers(df: pd.DataFrame, profiles: list[dict]) -> list[dict]:
    issues = []
    for p in profiles:
        col = p["name"]
        if p["inferred_type"] != prof.NUMERIC:
            continue
        values = prof.as_numeric(df[col]).dropna()
        if len(values) < 10:
            continue

        q1, q3 = values.quantile(0.25), values.quantile(0.75)
        iqr = q3 - q1
        by_iqr = (
            (values < q1 - config.IQR_MULTIPLIER * iqr)
            | (values > q3 + config.IQR_MULTIPLIER * iqr)
            if iqr > 0
            else pd.Series(False, index=values.index)
        )

        median = values.median()
        mad = (values - median).abs().median()
        by_mad = (
            ((values - median).abs() / (config.MAD_SCALE * mad) > config.ROBUST_Z_MAX)
            if mad > 0
            else pd.Series(False, index=values.index)
        )

        flagged = values.index[by_iqr | by_mad]
        if len(flagged) == 0:
            continue
        extreme = values.loc[flagged].abs().idxmax()
        issues.append(
            make_issue(
                id=f"outliers:{col}", check="C7_outliers", scope="column",
                severity=MEDIUM,
                title=f"{len(flagged)} outlying values in '{col}'",
                detail=(
                    f"{len(flagged)} rows sit far outside the rest of '{col}'. The most "
                    f"extreme is {values.loc[extreme]:g} against a median of {median:g}. "
                    "Measured against median absolute deviation, so a few large values "
                    "cannot inflate the threshold and hide inside it."
                ),
                column=col, row_indices=flagged, suggested_action="review",
                evidence={"by_iqr": int(by_iqr.sum()), "by_mad": int(by_mad.sum()),
                          "median": float(median)},
            )
        )
    return issues


def _implausible(df: pd.DataFrame, profiles: list[dict]) -> list[dict]:
    issues = []
    now = pd.Timestamp.now()
    for p in profiles:
        col = p["name"]
        kind = p["inferred_type"]

        if kind == prof.DATETIME:
            parsed = prof.as_datetime(df[col]).dropna()
            future = parsed.index[parsed > now]
            if len(future):
                issues.append(
                    make_issue(
                        id=f"future_dates:{col}", check="C8_implausible", scope="column",
                        severity=MEDIUM,
                        title=f"{len(future)} dates in '{col}' are in the future",
                        detail=(
                            f"{len(future)} rows carry a '{col}' later than today, the "
                            f"latest being {parsed.max().date()}. Usually a placeholder or "
                            "a parsing slip rather than a real date."
                        ),
                        column=col, row_indices=future, suggested_action="review",
                    )
                )
            continue

        if kind != prof.NUMERIC:
            continue
        values = prof.as_numeric(df[col]).dropna()
        if values.empty:
            continue

        positive_share = float((values >= 0).mean())
        negatives = values.index[values < 0]
        if len(negatives) and positive_share > config.IMPLAUSIBLE_POSITIVE_FRACTION:
            issues.append(
                make_issue(
                    id=f"unexpected_negative:{col}", check="C8_implausible", scope="column",
                    severity=MEDIUM,
                    title=f"{len(negatives)} negative values in an otherwise positive '{col}'",
                    detail=(
                        f"{pct(positive_share)} of '{col}' is zero or above, but "
                        f"{len(negatives)} rows are negative. In a column like this a "
                        "negative is normally a sentinel value standing in for missing."
                    ),
                    column=col, row_indices=negatives, suggested_action="review",
                )
            )

        # A value an order of magnitude past everything else is a different claim
        # from a statistical outlier: it says this one cell is on the wrong scale.
        if len(values) > 2:
            ordered = values.sort_values()
            second_largest = ordered.iloc[-2]
            runaway = values.index[
                (values > 0)
                & (values > config.IMPLAUSIBLE_RANGE_MULTIPLE * max(second_largest, 0))
            ]
            if len(runaway) and second_largest > 0:
                issues.append(
                    make_issue(
                        id=f"scale_break:{col}", check="C8_implausible", scope="column",
                        severity=MEDIUM,
                        title=f"'{col}' has a value {config.IMPLAUSIBLE_RANGE_MULTIPLE:g}x past the rest",
                        detail=(
                            f"The largest '{col}' is {values.max():g} while the next is "
                            f"{second_largest:g}. A gap this wide is usually a unit mix-up "
                            "or a stray digit, not a real reading."
                        ),
                        column=col, row_indices=runaway, suggested_action="review",
                    )
                )
    return issues


def _cramers_v(a: pd.Series, b: pd.Series) -> float:
    table = pd.crosstab(a, b)
    if min(table.shape) < 2:
        return 0.0
    chi2 = chi2_contingency(table, correction=False)[0]
    n = table.to_numpy().sum()
    denominator = min(table.shape[0] - 1, table.shape[1] - 1)
    return float(np.sqrt((chi2 / n) / denominator)) if denominator and n else 0.0


def _redundant_pairs(df: pd.DataFrame, profiles: list[dict], label_column: str | None) -> list[dict]:
    types = prof.types_by_column(profiles)
    issues = []

    numeric_cols = [c for c, t in types.items() if t == prof.NUMERIC and c != label_column]
    if len(numeric_cols) > 1:
        frame = pd.DataFrame({c: prof.as_numeric(df[c]).reindex(df.index) for c in numeric_cols})
        corr = frame.corr().abs()
        for i, a in enumerate(numeric_cols):
            for b in numeric_cols[i + 1:]:
                r = corr.loc[a, b]
                if pd.notna(r) and r > config.CORRELATION_HIGH:
                    issues.append(
                        make_issue(
                            id=f"redundant:{a}|{b}", check="C9_redundant", scope="column",
                            severity=LOW,
                            title=f"'{a}' and '{b}' carry the same information",
                            detail=(
                                f"The two correlate at {r:.3f}. One of them is a restatement "
                                "of the other, so keeping both adds width without adding signal."
                            ),
                            column=a, total_affected=len(df),
                            suggested_action="drop_column",
                            evidence={"pair": [a, b], "correlation": float(r), "measure": "pearson"},
                        )
                    )

    cat_cols = [
        c for c, t in types.items()
        if t in (prof.CATEGORICAL, prof.BOOLEAN)
        and c != label_column
        and df[c].nunique() <= config.MAX_CATEGORIES_FOR_ASSOCIATION
    ]
    for i, a in enumerate(cat_cols):
        for b in cat_cols[i + 1:]:
            v = _cramers_v(prof.present(df[a]), prof.present(df[b]).reindex(prof.present(df[a]).index))
            if v > config.CORRELATION_HIGH:
                issues.append(
                    make_issue(
                        id=f"redundant:{a}|{b}", check="C9_redundant", scope="column",
                        severity=LOW,
                        title=f"'{a}' and '{b}' carry the same information",
                        detail=(
                            f"Cramer's V between them is {v:.3f}, so knowing one tells you "
                            "the other. Keeping both duplicates the same split."
                        ),
                        column=a, total_affected=len(df), suggested_action="drop_column",
                        evidence={"pair": [a, b], "correlation": v, "measure": "cramers_v"},
                    )
                )
    return issues


def run(
    df: pd.DataFrame,
    profiles: list[dict],
    label_column: str | None = None,
    split_column: str | None = None,
) -> tuple[list[dict], list[dict]]:
    leakage, skipped = _single_feature_leakage(df, profiles, label_column, split_column)
    return [
        *leakage,
        *_missingness(df, profiles),
        *_sentinel_values(df, profiles),
        *_untrimmed(df, profiles),
        *_sparse_rows(df),
        *_constant(df, profiles),
        *_id_like(profiles, label_column),
        *_mixed_types(df, profiles),
        *_categorical_inconsistency(df, profiles),
        *_rare_categories(df, profiles),
        *_outliers(df, profiles),
        *_implausible(df, profiles),
        *_redundant_pairs(df, profiles, label_column),
    ], skipped


def _encode_single(df: pd.DataFrame, col: str, kind: str) -> np.ndarray | None:
    if kind == prof.CONSTANT:
        return None
    if kind in (prof.NUMERIC, prof.DATETIME):
        values = (
            prof.as_numeric(df[col])
            if kind == prof.NUMERIC
            else prof.as_datetime(df[col]).astype("int64", errors="ignore")
        ).reindex(df.index).astype(float)
        return values.fillna(values.median()).to_numpy().reshape(-1, 1)
    if kind == prof.TEXT:
        from ..encode import _encode_text

        return _encode_text(df, [col])
    codes = df[col].fillna("").astype(str).astype("category").cat.codes
    return codes.to_numpy().reshape(-1, 1)


def _single_feature_leakage(
    df: pd.DataFrame, profiles: list[dict], label_column: str | None, split_column: str | None
) -> tuple[list[dict], list[dict]]:
    if not label_column or label_column not in df.columns:
        return [], [{"check": "C10_leakage", "reason": "no label column was chosen"}]

    labels = df[label_column].where(~prof.missing_mask(df[label_column]))
    counts = labels.value_counts()
    if len(counts) < 2:
        return [], [{"check": "C10_leakage", "reason": "the label has fewer than two classes"}]

    keep = labels.notna() & ~labels.isin(counts[counts < config.MIN_CLASS_MEMBERS_FOR_CV].index)
    if keep.sum() < config.MISLABEL_MIN_ROWS or labels[keep].nunique() < 2:
        return [], [{"check": "C10_leakage", "reason": "too few rows to cross-validate"}]

    y = labels[keep].astype(str).to_numpy()
    # Always guessing the biggest class. On a label that is 99% one value every
    # column scores 0.99, and without this the check reports the whole dataset.
    majority = float(pd.Series(y).value_counts(normalize=True).iloc[0])
    folds = StratifiedKFold(config.CV_FOLDS, shuffle=True, random_state=0)

    issues = []
    for p in profiles:
        col = p["name"]
        if col in {label_column, split_column} or p["inferred_type"] == prof.CONSTANT:
            continue
        x = _encode_single(df[keep], col, p["inferred_type"])
        if x is None or x.shape[1] == 0:
            continue
        score = float(
            cross_val_score(
                DecisionTreeClassifier(max_depth=3, random_state=0), x, y, cv=folds
            ).mean()
        )
        if score <= config.LEAKAGE_ACCURACY or score <= majority + config.LEAKAGE_MIN_LIFT:
            continue
        issues.append(
            make_issue(
                id=f"leakage:{col}", check="C10_leakage", scope="column", severity=HIGH,
                title=f"'{col}' predicts '{label_column}' on its own at {score:.2f}",
                detail=(
                    f"A depth-3 tree on '{col}' alone recovers the label {pct(score)} of the "
                    f"time, against {pct(majority)} for always guessing the biggest class. "
                    "A single column this accurate is not a strong feature, it is the answer "
                    "copied into the input, usually written after the outcome was known. "
                    "Anything trained with it will score well here and fail on new data."
                ),
                column=col, total_affected=len(df), suggested_action="drop_column",
                evidence={"accuracy": score, "majority_baseline": majority},
            )
        )
    return issues, []
