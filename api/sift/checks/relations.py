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
from ..issue import HIGH, LOW, MEDIUM, make_issue

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


def _probe_rows(values: dict[str, pd.Series], columns: list[str]) -> list[dict[str, float]]:
    """A few rows where every numeric column is filled, spread through the file.

    The search below is cubic, and nearly every triple it considers is wrong.
    Checking a candidate against three rows first costs three multiplications
    and rejects it, where the real test costs a boolean mask and a pass over the
    column. Spread rather than taken from the top, because the first thirty rows
    of an export are often the least representative part of it.
    """
    frame = pd.DataFrame({c: values[c] for c in columns}).dropna()
    if len(frame) < config.ARITHMETIC_PROBE_ROWS:
        return []
    step = max(1, len(frame) // config.ARITHMETIC_PROBE_ROWS)
    picked = frame.iloc[::step].head(config.ARITHMETIC_PROBE_ROWS)
    return [{c: float(v) for c, v in row.items()} for _, row in picked.iterrows()]


def _agrees(left: float, right: float) -> bool:
    return abs(left - right) <= config.ARITHMETIC_TOLERANCE * max(1.0, abs(right))


def _arithmetic_relations(df: pd.DataFrame, profiles: list[dict]) -> list[dict]:
    numeric = [p["name"] for p in profiles if p["inferred_type"] == prof.NUMERIC]
    if len(numeric) < 3 or len(numeric) > config.ARITHMETIC_MAX_COLUMNS:
        return []

    values = {c: prof.as_numeric(df[c]).reindex(df.index) for c in numeric}
    present = {c: values[c].notna() for c in numeric}
    probes = _probe_rows(values, numeric)
    if not probes and len(numeric) > config.ARITHMETIC_MAX_COLUMNS_UNPROBED:
        return []
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
                    if probes and not all(
                        _agrees(fn(row[a], row[b]), row[target]) for row in probes
                    ):
                        continue
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
                    # How many different ways the relation was actually tested,
                    # which is not the same as how many rows tested it.
                    witnesses = int(
                        pd.MultiIndex.from_arrays(
                            [values[a][complete], values[b][complete]]
                        ).nunique()
                    )
                    proven = witnesses >= config.ARITHMETIC_MIN_DISTINCT

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
                                    + (
                                        ""
                                        if proven
                                        else f" Those {support} rows only test the rule "
                                        f"{witnesses} different ways, though, because the "
                                        "inputs take so few distinct values between them. A "
                                        "rule confirmed that few times can hold by accident, "
                                        "so this one is left for you: apply it if the formula "
                                        "is one you recognise."
                                    )
                                ),
                                column=column,
                                row_indices=df.index[fillable],
                                suggested_action="fill_from_formula",
                                evidence={
                                    "operation": operation,
                                    "left": left,
                                    "right": right,
                                    "support": support,
                                    "distinct_inputs": witnesses,
                                    "formula": label,
                                    "auto_apply": proven,
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


def _comparable(df: pd.DataFrame, profiles: list[dict]) -> dict[str, tuple[str, pd.Series]]:
    """Columns that can be put in order, with the kind of order they are in."""
    out: dict[str, tuple[str, pd.Series]] = {}
    for p in profiles:
        col = p["name"]
        if p["inferred_type"] == prof.DATETIME:
            parsed = prof.as_datetime(df[col]).reindex(df.index)
            if parsed.notna().any():
                out[col] = ("date", parsed)
        elif p["inferred_type"] == prof.NUMERIC:
            out[col] = ("number", prof.as_numeric(df[col]).reindex(df.index))
    return out


def _ranges_overlap(a: pd.Series, b: pd.Series) -> bool:
    """Whether two numeric columns are measuring the same kind of thing.

    Judged by their middle halves rather than their full ranges, so one extreme
    value in either column cannot manufacture an overlap. Measured against the
    wider of the two, because a narrow column sitting inside a wide one is a
    genuine pairing.
    """
    a_low, a_high = float(a.quantile(0.25)), float(a.quantile(0.75))
    b_low, b_high = float(b.quantile(0.25)), float(b.quantile(0.75))
    shared = min(a_high, b_high) - max(a_low, b_low)
    widest = max(a_high - a_low, b_high - b_low)
    if widest <= 0:
        return a_low == b_low
    return shared / widest > config.ORDERING_MIN_IQR_OVERLAP


def _ordering_rules(df: pd.DataFrame, profiles: list[dict]) -> list[dict]:
    """Rows that break an order the rest of the file keeps.

    A ship date is never before an order date, a maximum is never below its
    minimum, and an end is never before a start. None of that is written down
    anywhere, but a column pair that holds one way round on 3,000 rows and the
    other way round on four is not describing four unusual orders. It is
    describing four broken ones.

    This is the opposite shape to C12 and C13, where the rule is the finding and
    has to be exact. Here the exceptions are the finding, so the rule has to be
    established first: it holds on nearly every row, and the rows breaking it
    are few enough to be mistakes rather than a second population. Nothing is
    offered to fix, because which of the two dates is the wrong one is not
    something the file says.
    """
    kinds = _comparable(df, profiles)
    found = []
    for left, right in combinations(kinds, 2):
        kind, a = kinds[left]
        other, b = kinds[right]
        if kind != other:
            continue
        both = a.notna() & b.notna()
        support = int(both.sum())
        if support < config.ORDERING_MIN_SUPPORT:
            continue

        forward = a[both] <= b[both]
        share = float(forward.mean())
        # Whichever direction the file mostly keeps is the one being tested.
        if share < 0.5:
            left, right, a, b = right, left, b, a
            forward = a[both] <= b[both]
            share = float(forward.mean())
        if not config.ORDERING_MIN_SHARE <= share < 1.0:
            continue
        broken = forward.index[~forward]
        if len(broken) / support > config.ORDERING_MAX_VIOLATION_SHARE:
            continue
        # Two columns that are equal wherever they are both filled are C9's
        # finding, and the handful of rows where they differ is not an ordering.
        if float((a[both] == b[both]).mean()) > config.ORDERING_MIN_SHARE:
            continue
        if kind == "number" and not _ranges_overlap(a[both], b[both]):
            continue
        found.append((len(broken) / support, left, right, kind, share, support, broken))

    found.sort(key=lambda item: item[0])
    issues = []
    for _, left, right, kind, share, support, broken in found[: config.ORDERING_MAX_FINDINGS]:
        relation = "is never before" if kind == "date" else "is never above"
        issues.append(
            make_issue(
                id=f"ordering:{left}:{right}",
                check="C22_ordering_violation",
                scope="dataset",
                severity=HIGH if kind == "date" else MEDIUM,
                title=f"{len(broken)} rows have '{right}' before '{left}'"
                if kind == "date"
                else f"{len(broken)} rows have '{left}' above '{right}'",
                detail=(
                    f"'{left}' {relation} '{right}' in {share:.1%} of the {support} rows "
                    f"where both are filled. The other {len(broken)} go the other way. "
                    "A rule kept that consistently is a rule, and the rows breaking it "
                    "are more likely to be entry errors than real events. Which of the "
                    "two values is wrong is not something the file says, so these are "
                    "rows to look at rather than a fix to apply."
                ),
                column=right,
                row_indices=broken,
                suggested_action="review",
                evidence={
                    "left": left,
                    "right": right,
                    "kind": kind,
                    "holds_share": share,
                    "support": support,
                },
            )
        )
    return issues


def run(df: pd.DataFrame, profiles: list[dict]) -> tuple[list[dict], list[dict]]:
    # Sentinels are blanked first, or the rules they hide stay hidden. The row
    # indices that come back still refer to the original frame.
    clean = prof.without_sentinels(df)
    return [
        *_functional_dependencies(clean, profiles),
        *_arithmetic_relations(clean, profiles),
        *_ordering_rules(clean, profiles),
    ], []
