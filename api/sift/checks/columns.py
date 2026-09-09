"""Column-level checks C1 to C9. Pure pandas, no model fitting."""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import chi2_contingency

from .. import config, profile as prof
from ..issue import LOW, MEDIUM, make_issue, pct


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
                suggested_action="review",
                evidence={"missing_fraction": frac, "spellings": p["missing_tokens"]},
            )
        )
    return issues


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
        groups: dict[str, set] = {}
        for raw in values.unique():
            groups.setdefault(prof.normalise_text(raw), set()).add(raw)
        collisions = {k: v for k, v in groups.items() if len(v) > 1}
        if not collisions:
            continue

        counts = values.value_counts()
        rows, mapping = [], {}
        for key, raws in collisions.items():
            canonical = max(raws, key=lambda r: counts.get(r, 0))
            mapping[canonical] = sorted(raws)
            rows.extend(df.index[values.isin(raws - {canonical}).reindex(df.index, fill_value=False)])
        example = next(iter(mapping.items()))
        issues.append(
            make_issue(
                id=f"inconsistent:{col}", check="C5_categorical_inconsistency",
                scope="column", severity=MEDIUM,
                title=f"'{col}' has {len(collisions)} value spelled more than one way"
                if len(collisions) == 1
                else f"'{col}' has {len(collisions)} values spelled more than one way",
                detail=(
                    f"{', '.join(repr(v) for v in example[1])} are the same value written "
                    f"differently, and every model will treat them as separate categories. "
                    f"{len(rows)} rows use a non-canonical spelling."
                ),
                column=col, row_indices=rows, suggested_action="normalize_values",
                evidence={"canonical": {k: v for k, v in mapping.items()}},
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


def run(df: pd.DataFrame, profiles: list[dict], label_column: str | None = None) -> list[dict]:
    return [
        *_missingness(df, profiles),
        *_sparse_rows(df),
        *_constant(df, profiles),
        *_id_like(profiles, label_column),
        *_mixed_types(df, profiles),
        *_categorical_inconsistency(df, profiles),
        *_rare_categories(df, profiles),
        *_outliers(df, profiles),
        *_implausible(df, profiles),
        *_redundant_pairs(df, profiles, label_column),
    ]
