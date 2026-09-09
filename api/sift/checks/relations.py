"""Relationships between columns that can fill a gap by deduction.

This is what separates a generic cleaner from a hand-written script. Someone
cleaning a sales export by hand notices that price never varies within an item,
and that the total is always quantity times price, and uses both to reconstruct
missing cells. Neither observation needs domain knowledge - both are properties
of the data that can be measured.

The bar for both checks is exactness. A dependency that holds on 98% of rows is
a correlation, and filling from it would be imputation dressed up as deduction.
These only fire when the rule holds on every row where the inputs are present.
"""

from __future__ import annotations

from itertools import combinations, permutations

import numpy as np
import pandas as pd

from .. import config, profile as prof
from ..issue import LOW, MEDIUM, make_issue

OPERATIONS = {
    "product": (lambda a, b: a * b, "{c} = {a} x {b}"),
    "sum": (lambda a, b: a + b, "{c} = {a} + {b}"),
    "difference": (lambda a, b: a - b, "{c} = {a} - {b}"),
}


def _functional_dependencies(df: pd.DataFrame, profiles: list[dict]) -> list[dict]:
    kinds = {p["name"]: p["inferred_type"] for p in profiles}
    # A key has to be something with repeats. Identifiers and free text give one
    # group per row, where every dependency holds trivially and means nothing.
    keys = [
        p["name"]
        for p in profiles
        if (
            kinds[p["name"]] in (prof.CATEGORICAL, prof.BOOLEAN)
            and config.DEPENDENCY_MIN_KEYS <= p["n_unique"] <= config.DEPENDENCY_MAX_KEYS
        )
        # A numeric column with few distinct values behaves like a category and
        # can determine another column just as well. A price list, for instance.
        or (
            kinds[p["name"]] == prof.NUMERIC
            and config.DEPENDENCY_MIN_KEYS <= p["n_unique"] <= config.DEPENDENCY_MAX_NUMERIC_KEYS
        )
    ]
    targets = [
        p["name"]
        for p in profiles
        if kinds[p["name"]] not in (prof.ID_LIKE, prof.TEXT, prof.CONSTANT)
        and p["n_missing"] > 0
    ]
    if not keys or not targets:
        return []

    missing = {c: prof.missing_mask(df[c]) for c in set(keys) | set(targets)}
    issues = []

    for key in keys:
        for target in targets:
            if key == target:
                continue
            both = ~missing[key] & ~missing[target]
            if int(both.sum()) < config.DEPENDENCY_MIN_SUPPORT:
                continue

            pairs = df.loc[both, [key, target]]
            grouped = pairs.groupby(key, dropna=False)[target]
            distinct, support = grouped.nunique(), grouped.size()

            # Keys that settle on one value, with enough rows behind them to
            # believe it. Partial is allowed: the ambiguous keys are skipped
            # rather than disqualifying the whole relationship.
            decisive = (distinct == 1) & (support >= config.DEPENDENCY_MIN_KEY_SUPPORT)
            if not decisive.any():
                continue
            if decisive.mean() < config.DEPENDENCY_MIN_DECISIVE_SHARE:
                continue
            mapping = grouped.first()[decisive]

            fillable = missing[target] & ~missing[key] & df[key].isin(mapping.index)
            if not fillable.any():
                continue

            total_keys = int(len(distinct))
            partial = int(decisive.sum()) < total_keys
            how = (
                f"{int(decisive.sum())} of the {total_keys} values of '{key}' settle on a single "
                f"'{target}'"
                if partial
                else f"Every one of the {total_keys} values of '{key}' has exactly one '{target}'"
            )
            issues.append(
                make_issue(
                    id=f"dependency:{target}<-{key}",
                    check="C12_functional_dependency",
                    scope="column",
                    severity=MEDIUM,
                    title=f"'{target}' can be filled in from '{key}'",
                    detail=(
                        f"{how} across the {int(both.sum())} rows where both are present, with no "
                        f"exceptions. That recovers {int(fillable.sum())} missing values by "
                        "looking them up rather than guessing at them."
                        + (
                            " The remaining values of the key are ambiguous and are left alone."
                            if partial
                            else ""
                        )
                    ),
                    column=target,
                    row_indices=df.index[fillable],
                    suggested_action="fill_from_column",
                    evidence={
                        "source": key,
                        "mapping": {str(k): str(v) for k, v in mapping.items()},
                        "support": int(both.sum()),
                        "decisive_keys": int(decisive.sum()),
                        "total_keys": total_keys,
                    },
                )
            )
    return issues


def _arithmetic_relations(df: pd.DataFrame, profiles: list[dict]) -> list[dict]:
    numeric = [p["name"] for p in profiles if p["inferred_type"] == prof.NUMERIC]
    if len(numeric) < 3 or len(numeric) > config.ARITHMETIC_MAX_COLUMNS:
        return []

    values = {c: prof.as_numeric(df[c]).reindex(df.index) for c in numeric}
    present = {c: values[c].notna() for c in numeric}
    issues = []
    claimed: set[str] = set()

    for target in numeric:
        if target in claimed:
            continue
        for left, right in combinations([c for c in numeric if c != target], 2):
            for name, (fn, template) in OPERATIONS.items():
                # Subtraction is not commutative, so both orders are tried.
                orders = permutations((left, right)) if name == "difference" else [(left, right)]
                for a, b in orders:
                    complete = present[target] & present[a] & present[b]
                    support = int(complete.sum())
                    if support < config.ARITHMETIC_MIN_SUPPORT:
                        continue

                    expected = fn(values[a][complete], values[b][complete])
                    if not np.allclose(
                        expected, values[target][complete], rtol=config.ARITHMETIC_TOLERANCE,
                        atol=config.ARITHMETIC_TOLERANCE, equal_nan=False,
                    ):
                        continue
                    # A relation that is true only because everything is zero is
                    # arithmetically sound and practically useless.
                    if values[target][complete].nunique() < 2:
                        continue

                    label = template.format(c=target, a=a, b=b)
                    # An equation with three terms can be solved for any one of
                    # them. Filling only the left-hand side leaves recoverable
                    # cells sitting empty in the other two columns.
                    inverses = {
                        "product": [(a, "quotient", target, b), (b, "quotient", target, a)],
                        "sum": [(a, "difference", target, b), (b, "difference", target, a)],
                        "difference": [(a, "sum", target, b), (b, "difference", a, target)],
                    }[name]
                    plans = [(target, name, a, b), *inverses]

                    for column, operation, left, right in plans:
                        fillable = ~present[column] & present[left] & present[right]
                        if operation == "quotient":
                            fillable &= values[right].ne(0)
                        if not fillable.any():
                            continue
                        issues.append(
                            make_issue(
                                id=f"relation:{column}",
                                check="C13_arithmetic_relation",
                                scope="column",
                                severity=MEDIUM,
                                title=f"{int(fillable.sum())} missing '{column}' values follow from {label}",
                                detail=(
                                    f"'{label}' holds in all {support} rows where the three are "
                                    f"filled in, with no exceptions. Rearranged, that recovers "
                                    f"{int(fillable.sum())} missing '{column}' values by "
                                    "arithmetic rather than by guessing at them."
                                ),
                                column=column,
                                row_indices=df.index[fillable],
                                suggested_action="fill_from_formula",
                                evidence={
                                    "operation": operation,
                                    "left": left,
                                    "right": right,
                                    "support": support,
                                    "formula": label,
                                },
                            )
                        )
                    if not issues or issues[-1]["check"] != "C13_arithmetic_relation":
                        issues.append(
                            make_issue(
                                id=f"relation:{target}", check="C13_arithmetic_relation",
                                scope="column", severity=LOW,
                                title=f"{label}, on every row where all three are present",
                                detail=(
                                    f"'{label}' holds in all {support} rows where the three are "
                                    "filled in. Nothing is missing, so this is worth knowing "
                                    "rather than acting on: the column is derived, not measured."
                                ),
                                column=target, suggested_action="review",
                                evidence={"formula": label, "support": support},
                            )
                        )
                    claimed.add(target)
                    break
                if target in claimed:
                    break
            if target in claimed:
                break
    return issues


def run(df: pd.DataFrame, profiles: list[dict]) -> tuple[list[dict], list[dict]]:
    # Sentinels are blanked first, or the rules they hide stay hidden. The row
    # indices that come back still refer to the original frame.
    clean = prof.without_sentinels(df)
    return [*_functional_dependencies(clean, profiles), *_arithmetic_relations(clean, profiles)], []
