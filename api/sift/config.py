"""Every threshold the checks use. No logic here.

A number that decides whether a row gets flagged belongs in this file with a
comment saying what it means, so the whole tuning surface of the tool is one
screen long and reviewable.
"""

# --- input caps -------------------------------------------------------------
# Past these the request body exceeds Vercel's 4.5MB limit anyway, so reject
# with a clear message rather than timing out.
MAX_ROWS = 50_000
MAX_COLS = 200

# An issue carries row numbers for the UI to jump to. Beyond this the payload
# stops being useful and starts being expensive.
MAX_ROW_INDICES = 5_000

# --- type inference ---------------------------------------------------------
# A column whose values are nearly all distinct is an identifier, not a feature.
ID_UNIQUE_FRACTION = 0.95
# Mean whitespace-delimited tokens before a column counts as free text rather
# than a category.
TEXT_MIN_MEAN_TOKENS = 5
DATETIME_PARSE_FRACTION = 0.90
NUMERIC_PARSE_FRACTION = 0.90

# Strings that mean "no value" in exports from the wild. Compared lowercased and
# stripped. These are counted as missing by C1 and as non-numeric by C4, which is
# deliberate: the same cell is both a gap and a reason the column will not parse.
MISSING_TOKENS = frozenset(
    {"", "na", "n/a", "n.a.", "null", "none", "nil", "nan", "-", "--",
     "?", "unknown", "missing", "not available", "not applicable"}
)

# --- C1 missingness ---------------------------------------------------------
MISSING_WARN = 0.05
MISSING_HIGH = 0.30
# A row missing more than this share of its fields is usually a broken import.
SPARSE_ROW_FRACTION = 0.50

# --- C2 constant and near-constant ------------------------------------------
NEAR_CONSTANT_FRACTION = 0.99

# --- C4 mixed types ---------------------------------------------------------
# Both sides must clear this, or one stray typo in a clean numeric column would
# report as a type problem.
MIXED_TYPE_MIN_SHARE = 0.02

# --- C6 rare categories -----------------------------------------------------
RARE_CATEGORY_MIN = 5

# --- C7 numeric outliers ----------------------------------------------------
# Tukey's fence at 1.5 is for finding mild outliers in clean data. At 3.0 it
# flags the far tail only, which is what a data quality tool should report.
IQR_MULTIPLIER = 3.0
# Median absolute deviation, not standard deviation: a handful of extreme values
# inflate std enough to hide themselves inside their own threshold.
ROBUST_Z_MAX = 5.0
MAD_SCALE = 1.4826  # makes MAD a consistent estimator of sigma for normal data

# --- C8 implausible values --------------------------------------------------
IMPLAUSIBLE_POSITIVE_FRACTION = 0.99
IMPLAUSIBLE_RANGE_MULTIPLE = 10.0

# --- C9 redundant feature pairs ---------------------------------------------
CORRELATION_HIGH = 0.98
# Cramer's V over high-cardinality pairs is quadratic and rarely informative.
MAX_CATEGORIES_FOR_ASSOCIATION = 50

# --- D3 class imbalance -----------------------------------------------------
MIN_CLASS_FRACTION = 0.05
MIN_CLASS_ROWS = 10
CV_FOLDS = 5
