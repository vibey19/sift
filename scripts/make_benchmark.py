"""A spread of dirty CSVs, each paired with the file a careful person would produce.

Matching a hand-written script on one dataset proves the tool was tuned to that
dataset. This generates several archetypes with different faults in them, so the
claim being tested is that Sift generalises rather than that it was fitted.

Each archetype returns two frames: the dirty file, and the result of cleaning it
using only reasoning available from the data itself. The ideal deliberately does
not use domain knowledge the tool could not also derive - no hardcoded menus, no
"I happen to know this column is a percentage". Where the ideal drops rows, that
is noted, because Sift leaves that decision to the user.

    python scripts/make_benchmark.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent.parent / "benchmark"
SEED = 4242


def _sprinkle(rng, series: pd.Series, tokens: list[str], share: float) -> pd.Series:
    """Replace a share of the values with markers meaning "no value"."""
    out = series.astype(object).copy()
    n = int(len(out) * share)
    if n:
        rows = rng.choice(len(out), n, replace=False)
        out.iloc[rows] = rng.choice(tokens, n)
    return out


# --------------------------------------------------------------------------- 1
def retail_sales(rng):
    """Sentinels, a price determined by product, and total = quantity x price."""
    menu = {"Espresso": 2.5, "Latte": 3.5, "Muffin": 2.0, "Bagel": 3.0, "Juice": 4.0}
    n = 1200
    item = rng.choice(list(menu), n)
    qty = rng.integers(1, 6, n)
    price = np.array([menu[i] for i in item])

    ideal = pd.DataFrame(
        {
            "order_id": [f"O{i:05d}" for i in range(n)],
            "product": item,
            "quantity": qty,
            "unit_price": price,
            "line_total": np.round(qty * price, 2),
            "channel": rng.choice(["web", "counter"], n),
        }
    )
    dirty = ideal.astype(object).copy()
    dirty["unit_price"] = _sprinkle(rng, dirty["unit_price"], ["ERROR", "UNKNOWN"], 0.12)
    dirty["line_total"] = _sprinkle(rng, dirty["line_total"], ["", "n/a"], 0.10)
    dirty["quantity"] = _sprinkle(rng, dirty["quantity"], ["UNKNOWN"], 0.08)
    dirty["channel"] = _sprinkle(rng, dirty["channel"], ["", "UNKNOWN"], 0.15)

    ideal = ideal.copy()
    ideal["channel"] = ideal["channel"].where(
        ~dirty["channel"].isin(["", "UNKNOWN"]), "Unknown"
    )
    return dirty, ideal, "sentinels, a lookup and an equation"


# --------------------------------------------------------------------------- 2
def finance_ledger(rng):
    """Money written the way accountants write it."""
    n = 900
    amount = np.round(rng.normal(4000, 2500, n), 2)
    fee = np.round(np.abs(amount) * 0.015, 2)

    ideal = pd.DataFrame(
        {
            "txn": [f"T{i:06d}" for i in range(n)],
            "account": rng.choice(["ops", "payroll", "capex"], n),
            "amount": amount,
            "fee": fee,
            "rate": np.round(rng.uniform(0.5, 9.5, n), 2),
        }
    )

    def as_money(v):
        # Negatives in parentheses, thousands separators, a currency symbol.
        return f"(${abs(v):,.2f})" if v < 0 else f"${v:,.2f}"

    dirty = ideal.astype(object).copy()
    dirty["amount"] = [as_money(v) for v in amount]
    dirty["fee"] = [f"${v:,.2f}" for v in fee]
    dirty["rate"] = [f"{v}%" for v in ideal["rate"]]
    dirty["notes"] = ""  # a column that is entirely empty
    dirty["amount"] = _sprinkle(rng, dirty["amount"], ["N/A"], 0.06)

    ideal = ideal.copy()
    ideal["amount"] = ideal["amount"].where(~dirty["amount"].isin(["N/A"]), np.nan)
    return dirty, ideal, "currency symbols, separators, bracketed negatives, percentages"


# --------------------------------------------------------------------------- 3
def crm_contacts(rng):
    """Dates in four formats and booleans in five."""
    n = 800
    days = rng.integers(0, 900, n)
    dates = pd.Timestamp("2022-01-01") + pd.to_timedelta(days, unit="D")
    subscribed = rng.choice([True, False], n)

    ideal = pd.DataFrame(
        {
            "contact_id": [f"C{i:05d}" for i in range(n)],
            "country": rng.choice(["Finland", "Sweden", "Norway"], n),
            "signed_up": dates.strftime("%Y-%m-%d"),
            "subscribed": np.where(subscribed, "true", "false"),
            "score": rng.integers(0, 100, n),
        }
    )

    formats = ["%Y-%m-%d", "%d/%m/%Y", "%b %d, %Y", "%d-%b-%Y"]
    dirty = ideal.astype(object).copy()
    dirty["signed_up"] = [d.strftime(formats[i % len(formats)]) for i, d in enumerate(dates)]
    truthy = ["Y", "yes", "TRUE", "1", "True"]
    falsy = ["N", "no", "FALSE", "0", "False"]
    dirty["subscribed"] = [
        rng.choice(truthy) if s else rng.choice(falsy) for s in subscribed
    ]
    # Case and padding drift in the country column.
    dirty["country"] = [
        c.upper() if i % 7 == 0 else (f"  {c} " if i % 5 == 0 else c)
        for i, c in enumerate(dirty["country"])
    ]
    return dirty, ideal, "four date formats, five ways of writing true"


# --------------------------------------------------------------------------- 4
def sensor_readings(rng):
    """Units in the values and a numeric code standing in for missing."""
    n = 1500
    temp = np.round(rng.normal(21, 4, n), 1)
    humidity = np.round(rng.uniform(30, 70, n), 1)

    ideal = pd.DataFrame(
        {
            "reading_id": [f"R{i:06d}" for i in range(n)],
            "station": rng.choice(["north", "south", "east"], n),
            "temperature_c": temp,
            "humidity_pct": humidity,
            "firmware": "v2.1.0",  # never varies
        }
    )
    dirty = ideal.astype(object).copy()
    dirty["temperature_c"] = [f"{v} C" for v in temp]
    dirty["humidity_pct"] = [f"{v}%" for v in humidity]
    # -999 is the classic out-of-band code for "sensor did not report".
    rows = rng.choice(n, int(n * 0.07), replace=False)
    dirty.iloc[rows, dirty.columns.get_loc("temperature_c")] = "-999"

    ideal = ideal.copy()
    ideal.iloc[rows, ideal.columns.get_loc("temperature_c")] = np.nan
    return dirty, ideal, "units inside the values and -999 for missing"


# --------------------------------------------------------------------------- 5
def survey_responses(rng):
    """Categories spelled several ways, and a polite refusal that means missing."""
    n = 700
    answers = ["Strongly agree", "Agree", "Neutral", "Disagree", "Strongly disagree"]
    picked = rng.choice(answers, n)

    ideal = pd.DataFrame(
        {
            "response_id": [f"S{i:05d}" for i in range(n)],
            "region": rng.choice(["north", "south"], n),
            "q1": picked,
            "age_band": rng.choice(["18-24", "25-34", "35-49", "50+"], n),
            "comment": rng.choice(
                ["good service overall", "too slow at peak times", "friendly staff"], n
            ),
        }
    )
    dirty = ideal.astype(object).copy()
    dirty["q1"] = [
        a.upper() if i % 6 == 0 else (a.lower() if i % 5 == 0 else a)
        for i, a in enumerate(dirty["q1"])
    ]
    dirty["age_band"] = _sprinkle(rng, dirty["age_band"], ["Prefer not to say", ""], 0.18)

    ideal = ideal.copy()
    ideal["age_band"] = ideal["age_band"].where(
        ~dirty["age_band"].isin(["Prefer not to say", ""]), "Unknown"
    )
    return dirty, ideal, "case drift and a refusal that means no answer"


ARCHETYPES = {
    "retail_sales": retail_sales,
    "finance_ledger": finance_ledger,
    "crm_contacts": crm_contacts,
    "sensor_readings": sensor_readings,
    "survey_responses": survey_responses,
}


def main() -> None:
    OUT.mkdir(exist_ok=True)
    manifest = {}
    for name, build in ARCHETYPES.items():
        rng = np.random.default_rng(SEED)
        dirty, ideal, description = build(rng)
        dirty.to_csv(OUT / f"{name}_dirty.csv", index=False)
        ideal.to_csv(OUT / f"{name}_ideal.csv", index=False)
        manifest[name] = {"description": description, "rows": len(dirty), "cols": len(dirty.columns)}
        print(f"  {name:20s} {len(dirty):5d} x {len(dirty.columns):2d}  {description}")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
