"""Generate the two sample datasets, with every defect recorded by row index.

The same two dataframes are used three ways: as pytest fixtures, as the data the
thresholds in config.py get tuned against, and as the sample files the app offers
from its empty state. Because the defects are recorded rather than eyeballed, a
check can be tested on recall ("found 34 of the 40 rows I flipped") instead of on
whether it merely returned something.

Run directly to write samples/*.csv and samples/_truth.json.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 8117
SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"

N_CHURN = 3000
N_REVIEWS = 1500


class _IndexPool:
    # Hands out disjoint sets of row indices. Defects that would confound each
    # other during testing (a flipped label sitting on a duplicated row) must not
    # land on the same row, and drawing from one shuffled permutation is the
    # cheapest way to guarantee that.
    def __init__(self, n: int, rng: np.random.Generator):
        self._order = list(rng.permutation(n))
        self._cursor = 0

    def take(self, k: int) -> list[int]:
        chunk = self._order[self._cursor : self._cursor + k]
        self._cursor += k
        if len(chunk) < k:
            raise ValueError("index pool exhausted")
        return sorted(int(i) for i in chunk)


def make_churn(seed: int = SEED) -> tuple[pd.DataFrame, dict]:
    rng = np.random.default_rng(seed)
    n = N_CHURN

    tenure = rng.integers(1, 72, n)
    monthly = np.round(rng.normal(70, 25, n).clip(20.0, 150.0), 2)
    tickets = rng.poisson(1.2, n)
    contract = rng.choice(["Monthly", "Annual", "Two year"], n, p=[0.55, 0.30, 0.15])
    plan = rng.choice(["Basic", "Standard", "Premium"], n, p=[0.40, 0.40, 0.20])

    # Churn is a real function of the features, not noise. Without a learnable
    # signal the cross-validated model in R1 scores at chance and cannot flag
    # anything, which would make the mislabel fixture useless.
    z = (
        -0.055 * tenure
        + 0.015 * (monthly - 70.0)
        + 0.55 * tickets
        + 1.10 * (contract == "Monthly")
        + 0.35
    )
    churned = (rng.random(n) < 1.0 / (1.0 + np.exp(-z))).astype(int)
    true_labels = churned.copy()

    signup = pd.Timestamp("2024-06-01") - pd.to_timedelta(tenure * 30, unit="D")

    df = pd.DataFrame(
        {
            "customer_id": [f"C{i:06d}" for i in range(n)],
            "signup_date": signup.strftime("%Y-%m-%d"),
            "region": "EU",
            "plan": plan,
            "contract": contract,
            "tenure_months": tenure,
            "monthly_charges": monthly,
            # A currency-converted copy of monthly_charges. Duplicate columns like
            # this survive most real exports and are what C9 is looking for.
            "monthly_charges_eur": np.round(monthly * 0.92, 2),
            "support_tickets": tickets,
            "discount_pct": rng.integers(0, 30, n).astype(object),
            "email": [f"user{i}@example.com" for i in range(n)],
            "split": rng.choice(["train", "test"], n, p=[0.75, 0.25]),
            "churned": churned,
        }
    )

    # The reason is written by the retention team when someone actually leaves, so
    # it tracks the true outcome and not the typo-ridden label column. That keeps
    # it a near-perfect predictor (the leak C10 must catch) while still disagreeing
    # with the 40 rows whose label was flipped, which is what lets R1 find them.
    reasons = rng.choice(["price", "moved", "competitor", "service"], n)
    df["cancellation_reason"] = np.where(true_labels == 1, reasons, "")

    pool = _IndexPool(n, rng)
    mislabelled = pool.take(40)
    outliers = pool.take(12)
    exact_src = pool.take(30)
    near_src = pool.take(20)
    sparse_rows = pool.take(8)
    # C4 only fires when neither the numeric nor the string side is under 2%,
    # so this has to clear that floor to be a usable fixture for it.
    mixed_type = pool.take(100)
    implausible = pool.take(10)
    rare_cat = pool.take(3)

    df.loc[mislabelled, "churned"] = 1 - df.loc[mislabelled, "churned"]
    df.loc[outliers, "tenure_months"] = df.loc[outliers, "tenure_months"] * 100

    # Same plan, four spellings.
    variants = [" Premium ", "premium", "PREMIUM"]
    premium_rows = df.index[df["plan"] == "Premium"].to_numpy()
    for i, row in enumerate(rng.choice(premium_rows, 90, replace=False)):
        df.at[int(row), "plan"] = variants[i % len(variants)]
    df.loc[rare_cat, "plan"] = "Enterprise"

    df.loc[rng.choice(n, int(n * 0.35), replace=False), "email"] = np.nan
    df.loc[mixed_type, "discount_pct"] = rng.choice(["N/A", "none", "unknown"], len(mixed_type))
    df.loc[implausible, "signup_date"] = "2031-04-02"
    for col in ["plan", "contract", "monthly_charges", "support_tickets", "email", "discount_pct"]:
        df.loc[sparse_rows, col] = np.nan

    # Copies are appended after the in-place corruption so a duplicated row is a
    # faithful copy of what it duplicates, the way a real double-import behaves.
    exact_rows = df.loc[exact_src].copy()
    near_rows = df.loc[near_src].copy()
    near_rows["tenure_months"] = near_rows["tenure_months"] + 1

    train_pool = [i for i in df.index[df["split"] == "train"] if i not in set(exact_src + near_src)]
    overlap_src = sorted(int(i) for i in rng.choice(train_pool, 25, replace=False))
    overlap_rows = df.loc[overlap_src].copy()
    overlap_rows["split"] = "test"

    df = pd.concat([df, exact_rows, near_rows, overlap_rows], ignore_index=True)

    exact_copy = list(range(n, n + 30))
    near_copy = list(range(n + 30, n + 50))
    overlap_copy = list(range(n + 50, n + 75))

    truth = {
        "n_rows": int(len(df)),
        "label_column": "churned",
        "split_column": "split",
        "mislabelled_idx": mislabelled,
        "outlier_idx": outliers,
        "exact_dup_idx": sorted(exact_src + exact_copy),
        "near_dup_idx": sorted(near_src + near_copy),
        "overlap_idx": sorted(overlap_src + overlap_copy),
        "sparse_row_idx": sparse_rows,
        "implausible_idx": implausible,
        "leaked_cols": ["cancellation_reason"],
        "constant_cols": ["region"],
        "id_cols": ["customer_id"],
        "missing_cols": ["email"],
        "dirty_cat_cols": ["plan"],
        "mixed_type_cols": ["discount_pct"],
        "rare_cat_cols": ["plan"],
        "redundant_pairs": [["monthly_charges", "monthly_charges_eur"]],
    }
    return df, truth


_ADJ = {
    "positive": ["excellent", "fantastic", "perfect", "flawless", "superb",
                 "outstanding", "solid", "brilliant", "sturdy", "impressive"],
    "negative": ["terrible", "awful", "useless", "broken", "flimsy",
                 "shoddy", "unusable", "defective", "dreadful", "cheap"],
    "neutral": ["okay", "average", "acceptable", "adequate", "unremarkable",
                "fine", "serviceable", "passable", "ordinary", "middling"],
}

_SECOND = {
    "positive": ["I would order another without thinking twice.",
                 "It has become the one I reach for every morning.",
                 "Packaging was tidy and nothing was scratched.",
                 "Battery life beat what the listing promised.",
                 "My partner liked it enough to ask for one.",
                 "Support answered my question the same afternoon.",
                 "It has survived two house moves already.",
                 "Worth every bit of what I paid."],
    "negative": ["I have started a return and want my money back.",
                 "It stopped working entirely on the fourth day.",
                 "The listing photos do not match what turned up.",
                 "Support have ignored two emails so far.",
                 "It rattles badly whenever it is switched on.",
                 "Mine arrived with a crack down one side.",
                 "I would not put this in front of a guest.",
                 "Save your money and buy something else."],
    "neutral": ["It does what it says and nothing beyond that.",
                "I neither regret it nor recommend it.",
                "Fine for the money, forgettable otherwise.",
                "There are better options if you can spend more.",
                "It sits in a drawer more often than not.",
                "No complaints, but no enthusiasm either.",
                "It works, though the manual was useless.",
                "About what I expected at this price."],
}

_FRAMES = [
    "The {noun} arrived on day {days} and the build quality felt {adj}.",
    "I have used this {noun} for {weeks} weeks now and it is {adj}.",
    "Honestly the {noun} was {adj} for the {price} pounds I paid.",
    "Setup took about {mins} minutes and the whole {noun} felt {adj}.",
    "Compared to the {noun} it replaced {weeks} weeks ago this one is {adj}.",
    "Bought the {noun} for my {room} {weeks} weeks back and found it {adj}.",
    "After {weeks} weeks of daily use the {noun} still looks {adj}.",
    "Ordered the {noun} on a whim for {price} pounds and the finish is {adj}.",
]

_NOUNS = ["headset", "kettle", "monitor", "backpack", "keyboard", "lamp",
          "blender", "mousepad", "speaker", "toaster", "chair", "router"]
_ROOMS = ["kitchen", "home office", "spare room", "studio", "workshop", "hallway"]

# Short reviews that reuse stock phrasing. They sit close together under cosine
# similarity without being duplicates, which is the noise that makes the
# near-duplicate threshold a real choice rather than an obvious one.
_STOCK = [
    "Good product. Would buy again.",
    "Good product. Would order again.",
    "Great product, would buy again!",
    "Nice product. Will buy again.",
    "Does the job. No complaints.",
    "Does the job, no complaints here.",
]


def make_reviews(seed: int = SEED) -> tuple[pd.DataFrame, dict]:
    rng = np.random.default_rng(seed + 1)
    n = N_REVIEWS

    sentiment = rng.choice(["negative", "neutral", "positive"], n, p=[0.30, 0.25, 0.45])
    # Two sentences drawn from per-sentiment pools with numeric detail mixed in.
    # The combinatorial space has to be far larger than the row count, or a large
    # share of rows collide by accident and bury the 25 planted near-duplicates.
    bodies = []
    for s in sentiment:
        frame = _FRAMES[int(rng.integers(len(_FRAMES)))]
        first = frame.format(
            noun=_NOUNS[int(rng.integers(len(_NOUNS)))],
            adj=_ADJ[s][int(rng.integers(len(_ADJ[s])))],
            days=int(rng.integers(1, 15)),
            weeks=int(rng.integers(2, 30)),
            price=int(rng.integers(12, 190)),
            mins=int(rng.integers(5, 60)),
            room=_ROOMS[int(rng.integers(len(_ROOMS)))],
        )
        second = _SECOND[s][int(rng.integers(len(_SECOND[s])))]
        bodies.append(f"{first} {second}")

    # Rating tracks sentiment but not perfectly - roughly one review in seven
    # leaves a score that does not match its tone. Without that slack the star
    # rating is a second perfect leak and the text stops being what R1 learns
    # from, which is the whole reason this dataset exists.
    rating_by = {"negative": [1, 2], "neutral": [3], "positive": [4, 5]}
    ratings = [
        int(rng.integers(1, 6)) if rng.random() < 0.15 else int(rng.choice(rating_by[s]))
        for s in sentiment
    ]

    df = pd.DataFrame(
        {
            "review_id": [f"R{i:06d}" for i in range(n)],
            "product_category": rng.choice(["Audio", "Kitchen", "Office"], n),
            "review_body": bodies,
            "rating": ratings,
            "verified": rng.choice([True, False], n, p=[0.8, 0.2]),
            "split": rng.choice(["train", "test"], n, p=[0.75, 0.25]),
            "sentiment": sentiment,
        }
    )

    pool = _IndexPool(n, rng)
    stock_rows = pool.take(60)
    mislabelled = pool.take(30)
    near_src = pool.take(25)
    case_variant = pool.take(35)
    space_variant = pool.take(25)

    # Each stock row keeps a recycled opening but gets its own trailing detail, so
    # they cluster without being copies. Cycling the bare phrases would make these
    # exact duplicates and they would stop being the ambiguous middle band that
    # the near-duplicate threshold has to be chosen against.
    tails = ["Delivery took {d} days.", "Arrived {d} days early.",
             "Ordered {d} of them.", "Second one in {d} months.",
             "Used it for {d} weeks so far."]
    for i, row in enumerate(stock_rows):
        tail = tails[int(rng.integers(len(tails)))].format(d=int(rng.integers(2, 40)))
        df.at[row, "review_body"] = _STOCK[i % len(_STOCK)] + " " + tail

    order = ["negative", "neutral", "positive"]
    df.loc[mislabelled, "sentiment"] = [
        order[(order.index(s) + 1) % 3] for s in df.loc[mislabelled, "sentiment"]
    ]

    # Casing and stray whitespace turn a 3-class problem into a 5-class one
    # without anything visibly changing in a spreadsheet.
    df.loc[case_variant, "sentiment"] = df.loc[case_variant, "sentiment"].str.capitalize()
    df.loc[space_variant, "sentiment"] = " " + df.loc[space_variant, "sentiment"]

    # A resubmitted review with one figure corrected. Changing a single token out
    # of roughly thirty leaves cosine similarity around 0.96, which is above the
    # stock-phrase noise and below an exact copy - the gap the threshold has to
    # land in. Every frame carries a number so this always applies.
    near_rows = df.loc[near_src].copy()
    near_rows["review_body"] = [
        re.sub(r"\d+", lambda m: str(int(m.group()) + 3), body, count=1)
        for body in near_rows["review_body"]
    ]
    df = pd.concat([df, near_rows], ignore_index=True)

    truth = {
        "n_rows": int(len(df)),
        "label_column": "sentiment",
        "split_column": "split",
        "mislabelled_idx": mislabelled,
        "near_dup_idx": sorted(near_src + list(range(n, n + 25))),
        "stock_phrase_idx": stock_rows,
        "dirty_cat_cols": ["sentiment"],
        "id_cols": ["review_id"],
        "text_cols": ["review_body"],
    }
    return df, truth


def main() -> None:
    SAMPLES_DIR.mkdir(exist_ok=True)
    truths = {}
    for name, builder in (("churn_dirty", make_churn), ("reviews_dirty", make_reviews)):
        df, truth = builder()
        df.to_csv(SAMPLES_DIR / f"{name}.csv", index=False)
        truths[name] = truth
        print(f"{name}.csv  {len(df)} rows x {len(df.columns)} cols")

    (SAMPLES_DIR / "_truth.json").write_text(json.dumps(truths, indent=2))
    print(f"_truth.json written to {SAMPLES_DIR}")


if __name__ == "__main__":
    main()
