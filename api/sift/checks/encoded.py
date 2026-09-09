"""C15 to C18: values that are the right thing written the wrong way.

Everything here is a formatting fault rather than a data fault. The number is
correct, it just has a currency symbol in front of it. The date is right, it was
simply typed by three different people. Undoing that is mechanical, and it is
most of what a hand-written cleaning script spends its lines on.
"""

from __future__ import annotations

import pandas as pd

from .. import config, formats, profile as prof
from ..issue import LOW, MEDIUM, make_issue


def _formatted_numbers(df: pd.DataFrame, profiles: list[dict]) -> list[dict]:
    issues = []
    for p in profiles:
        col = p["name"]
        # A column pandas already reads as numbers needs nothing doing to it.
        if p["inferred_type"] in (prof.NUMERIC, prof.DATETIME, prof.CONSTANT, prof.TEXT):
            continue
        values = prof.present(df[col])
        if len(values) < config.FORMAT_MIN_VALUES:
            continue

        parsed = values.map(formats.parse_number)
        share = float(parsed.notna().mean())
        if share < config.FORMAT_MIN_SHARE:
            continue
        dressed = values[values.map(formats.needs_reformatting)]
        if len(dressed) < config.FORMAT_MIN_VALUES:
            continue

        # What is about to be thrown away. Stripping a unit is the one thing
        # this fix does that cannot be undone by looking at the result: 45 kg
        # and 45 lb both become 45, and nothing in the file remembers which.
        parts = [p for p in values.map(formats.number_parts) if p]
        units = sorted({p["unit"] for p in parts if p["unit"]})
        symbols = sorted({p["symbol"] for p in parts if p["symbol"]})
        # A percent sign is a unit that also implies a convention, and the two
        # conventions differ by a factor of a hundred.
        percent = "%" in units
        mixed = len(units) > 1 or len(symbols) > 1

        examples = list(dressed.value_counts().index[:4])
        detail = (
            f"{len(dressed)} of the {len(values)} filled values in '{col}' are numbers "
            f"carrying a symbol, a separator or a unit, like {', '.join(repr(e) for e in examples[:3])}. "
            "Written that way the column loads as text, so nothing can be summed, "
            "averaged or compared until the formatting comes off."
        )
        if mixed:
            found = ", ".join(repr(u) for u in (units + symbols)[:4])
            detail += (
                f" This column does not use one, it uses {len(units) + len(symbols)}: "
                f"{found}. Taking them off would make every value the same kind of number "
                "when they are not, and nothing left in the file would say which was which. "
                "So this is left for you: split the column, or convert to one unit, and "
                "then the formatting can come off safely."
            )
        else:
            worn = (symbols + units)[0] if (symbols or units) else ""
            if worn and not percent:
                detail += (
                    f" Every value carries the same {'symbol' if worn in symbols else 'unit'}, "
                    f"{worn!r}, so removing it loses nothing the column did not already say "
                    "once. It is worth putting into the column name."
                )
            if percent:
                detail += (
                    " Note which convention this leaves you in: '45%' becomes 45, not 0.45. "
                    "That is the reading most spreadsheets use and the opposite of the one "
                    "most statistical code expects, so divide by a hundred if you need the "
                    "other."
                )

        issues.append(
            make_issue(
                id=f"format_number:{col}",
                check="C15_formatted_numbers",
                scope="column",
                severity=MEDIUM,
                title=(
                    f"'{col}' mixes {len(symbols)} currencies"
                    if mixed and len(symbols) > 1
                    else f"'{col}' mixes {len(units)} different units"
                    if mixed
                    else f"'{col}' holds numbers that will not parse as numbers"
                ),
                detail=detail,
                column=col,
                row_indices=dressed.index,
                suggested_action="reformat_number",
                evidence={
                    "examples": [str(e) for e in examples],
                    "parse_share": share,
                    "units": units,
                    "symbols": symbols,
                    "percent": percent,
                    "auto_apply": not mixed,
                },
            )
        )
    return issues


def _mixed_dates(df: pd.DataFrame, profiles: list[dict]) -> list[dict]:
    issues = []
    for p in profiles:
        col = p["name"]
        if p["inferred_type"] in (prof.NUMERIC, prof.CONSTANT, prof.ID_LIKE):
            continue
        values = prof.present(df[col])
        if len(values) < config.FORMAT_MIN_VALUES:
            continue

        styles = values.map(formats.date_style)
        if float(styles.notna().mean()) < config.FORMAT_MIN_SHARE:
            continue
        seen = styles.dropna().value_counts()
        # One consistent format that is already ISO needs no help.
        if len(seen) < 2 and seen.index[0] == "iso":
            continue

        dayfirst = formats.needs_dayfirst(values)
        # Numeric dates where no first number exceeds 12 fit both readings.
        numeric_dates = (styles == "numeric").sum()
        ambiguous = bool(numeric_dates) and not dayfirst
        rewritten = values.map(lambda v: formats.parse_date(v, dayfirst))
        changed = values[rewritten.notna() & (rewritten != values)]
        if len(changed) < config.FORMAT_MIN_VALUES:
            continue

        how = (
            f"{len(seen)} different formats"
            if len(seen) > 1
            else f"the {seen.index[0]} format"
        )
        issues.append(
            make_issue(
                id=f"format_date:{col}",
                check="C16_mixed_date_formats",
                scope="column",
                severity=MEDIUM if len(seen) > 1 else LOW,
                title=f"'{col}' is written in {how}",
                detail=(
                    f"Dates in '{col}' appear as {', '.join(seen.index[:3])}"
                    + (
                        ". Sorting that column sorts it alphabetically, and any two of those "
                        "formats disagree about which number is the month."
                        if len(seen) > 1
                        else ". Rewriting to ISO makes it sortable and unambiguous."
                    )
                    + (
                        " Days above 12 appear in the first position, so the numeric dates are "
                        "day-first and there is nothing to decide."
                        if dayfirst
                        else ""
                    )
                    + (
                        f" No first number in the {numeric_dates} numeric dates exceeds 12, so "
                        "01/02/2023 could be the first of February or the second of January and "
                        "the file does not say which. Rewriting them would be a coin flip, so "
                        "this is left for you: apply it if you know the convention."
                        if ambiguous
                        else ""
                    )
                ),
                column=col,
                row_indices=changed.index,
                suggested_action="reformat_date",
                evidence={
                    "styles": {str(k): int(v) for k, v in seen.items()},
                    "dayfirst": bool(dayfirst),
                    "auto_apply": not ambiguous,
                },
            )
        )
    return issues


def _inconsistent_booleans(df: pd.DataFrame, profiles: list[dict]) -> list[dict]:
    issues = []
    for p in profiles:
        col = p["name"]
        if p["inferred_type"] in (prof.TEXT, prof.CONSTANT, prof.ID_LIKE, prof.DATETIME):
            continue
        values = prof.present(df[col])
        if len(values) < config.FORMAT_MIN_VALUES:
            continue

        parsed = values.map(formats.parse_boolean)
        if float(parsed.notna().mean()) < config.BOOLEAN_MIN_SHARE:
            continue
        spellings = values.str.strip().str.lower().nunique()
        if spellings <= 2:
            continue  # already written one way for true and one for false

        forms = list(values.value_counts().index[:6])
        issues.append(
            make_issue(
                id=f"boolean:{col}",
                check="C17_inconsistent_booleans",
                scope="column",
                severity=MEDIUM,
                title=f"'{col}' writes true and false {spellings} different ways",
                detail=(
                    f"'{col}' contains {', '.join(repr(f) for f in forms[:5])}. They mean two "
                    "things, but every tool that reads the file will see "
                    f"{spellings} categories, and grouping on it will split rows that belong "
                    "together."
                ),
                column=col,
                row_indices=values.index,
                suggested_action="normalize_boolean",
                evidence={"forms": [str(f) for f in forms], "distinct": int(spellings)},
            )
        )
    return issues


def _out_of_band_codes(df: pd.DataFrame, profiles: list[dict]) -> list[dict]:
    """A number standing in for "no reading", like -999 or 9999."""
    issues = []
    for p in profiles:
        col = p["name"]
        if p["inferred_type"] != prof.NUMERIC:
            continue
        values = prof.as_numeric(df[col]).dropna()
        if len(values) < config.OUT_OF_BAND_MIN_VALUES:
            continue

        counts = values.value_counts()
        median = values.median()
        spread = (values - median).abs().median()
        if spread <= 0:
            continue

        for candidate, times in counts.items():
            share = times / len(values)
            if times < config.OUT_OF_BAND_MIN_COUNT or share > config.OUT_OF_BAND_MAX_SHARE:
                continue
            # Far outside the data and repeated exactly: a placeholder, not a
            # reading. A real measurement does not land on the same extreme
            # value dozens of times.
            distance = abs(candidate - median) / (config.MAD_SCALE * spread)
            if distance < config.OUT_OF_BAND_MIN_DISTANCE:
                continue
            if candidate in (0, 1, -1) and abs(median) < 10:
                continue  # too ordinary to accuse

            rows = values.index[values == candidate]
            issues.append(
                make_issue(
                    id=f"out_of_band:{col}",
                    check="C18_out_of_band_code",
                    scope="column",
                    severity=MEDIUM,
                    title=f"'{col}' uses {candidate:g} to mean no reading",
                    detail=(
                        f"{times} rows hold exactly {candidate:g} in '{col}', which sits "
                        f"{distance:.0f} deviations from the median of {median:g}. A real "
                        "measurement does not land on the same extreme value that often, so "
                        "this is a placeholder. Left as a number it drags every average and "
                        "every model that reads the column."
                    ),
                    column=col,
                    row_indices=rows,
                    suggested_action="blank_values",
                    evidence={"forms": [str(df.at[rows[0], col])], "code": float(candidate)},
                )
            )
            break
    return issues


def _markup_in_text(df: pd.DataFrame, profiles: list[dict]) -> list[dict]:
    """Scraped text with the page still attached.

    A review body carrying <br> and &amp; is the HTML it was lifted from rather
    than what anyone wrote. Left in, it is counted as words by any model reading
    the column, and read by any human as noise.
    """
    issues = []
    for p in profiles:
        col = p["name"]
        if p["inferred_type"] not in (prof.TEXT, prof.CATEGORICAL):
            continue
        values = prof.present(df[col])
        if len(values) < config.FORMAT_MIN_VALUES:
            continue
        hits = values.str.contains(formats.MARKUP, regex=True)
        count = int(hits.sum())
        if count < config.MARKUP_MIN_COUNT or count / len(values) < config.MARKUP_MIN_SHARE:
            continue

        seen = {m.group(0) for v in values[hits].head(200) for m in formats.MARKUP.finditer(str(v))}
        issues.append(
            make_issue(
                id=f"markup:{col}",
                check="C21_markup",
                scope="column",
                severity=MEDIUM,
                title=f"{count} values in '{col}' still contain HTML",
                detail=(
                    f"{count} of the {len(values)} filled values in '{col}' carry tags or "
                    "character entities, which is what text looks like when it has been "
                    "lifted off a web page rather than written. Every model reading the "
                    "column counts them as words, and every person reading it has to "
                    "ignore them."
                ),
                column=col,
                row_indices=values.index[hits],
                suggested_action="strip_markup",
                evidence={"examples": sorted(seen)[:4]},
            )
        )
    return issues


def run(df: pd.DataFrame, profiles: list[dict]) -> tuple[list[dict], list[dict]]:
    return (
        [
            *_formatted_numbers(df, profiles),
            *_mixed_dates(df, profiles),
            *_inconsistent_booleans(df, profiles),
            *_out_of_band_codes(df, profiles),
            *_markup_in_text(df, profiles),
        ],
        [],
    )
