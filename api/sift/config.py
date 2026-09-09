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

# --- shared encoding --------------------------------------------------------
TFIDF_MAX_FEATURES = 20_000
TFIDF_MIN_DF = 2
TFIDF_NGRAM_RANGE = (1, 2)
SVD_COMPONENTS = 128

# --- D2 near-duplicate rows -------------------------------------------------
# Exact cosine similarity is quadratic. Past this it needs approximate nearest
# neighbours, and below it exact is faster than building the index would be.
NEAR_DUP_MAX_ROWS = 20_000
NEAR_DUP_CHUNK = 1_000

# --- C10 single-feature leakage ---------------------------------------------
# A column only counts as leaking if it beats always guessing the biggest class
# by this much. On a 99%-one-class label every column scores 0.99 and the check
# would report the whole dataset.
LEAKAGE_MIN_LIFT = 0.05

# --- R1 probable mislabels --------------------------------------------------
# Below this there is not enough data to cross-validate a useful model.
MISLABEL_MIN_ROWS = 50
# Stratified k-fold cannot place a member of a smaller class in every fold. The
# failure is silent, so these classes are dropped and reported instead.
MIN_CLASS_MEMBERS_FOR_CV = 5

# --- D2/D4 near-duplicate matching ------------------------------------------
# A near-duplicate is the same record entered twice: every field agrees except
# one, and that one is close rather than different. Cosine similarity over an
# encoded matrix cannot express that on tabular data - with a handful of one-hot
# columns, unrelated rows already sit around 0.5 and the tail of coincidental
# matches swamps the real pairs at any threshold.
#
# Candidate pairs come from hashing each leave-one-column-out view of the frame,
# which is linear rather than quadratic. The differing field is then judged.
#
# Measured against the column's interquartile spread, not the value's own size:
# a one-month difference is 33% of a tenure of 3 and 1.7% of a tenure of 60, and
# the relative version missed 6 of 40 planted pairs because of it.
NEAR_DUP_NUMERIC_TOLERANCE = 0.05
# A bucket larger than this is a mass of identical rows, already reported by D1.
NEAR_DUP_MAX_GROUP = 50

# --- thresholds set by hand against the sample datasets ---------------------
# Chosen by sweeping each one against the recorded defects in samples/.
# Reproduce with: python scripts/tune.py

# Text similarity required of the one field two near-duplicate rows differ on.
# On the reviews set 0.70 recovers all 50 planted rows with no false pairs, and
# so does 0.60, so the low end is flat. 0.75 drops to 42, 0.80 to 24, and the
# 0.97 this started at finds 6. That old value was carried over from the cosine
# design this check replaced, where the threshold had to separate duplicates
# from the entire dataset; here the field-agreement structure has already done
# that, and the threshold only confirms the differing text is close.
NEAR_DUP_THRESHOLD = 0.70

# A column scoring above this against the label, on its own, is the answer
# rather than a feature. The planted leak scores 0.987 and the strongest honest
# feature in either sample is a star rating at 0.859, so anything in that band
# separates them. 0.95 sits in the middle of it. 0.98 also works but clears the
# planted leak by only 0.007, which would miss a slightly weaker real one.
LEAKAGE_ACCURACY = 0.95

# A row is flagged when the model gives its stated label less than the first
# number and gives something else more than the second. At these values 39 of
# 40 planted mislabels come back on churn with no false flags, and 30 of 30 on
# reviews. Loosening to 0.20/0.50 recovers the fortieth row but admits two
# false ones; tightening to 0.05/0.90 returns the same 39 and buys nothing.
MISLABEL_P_GIVEN_MAX = 0.10
MISLABEL_P_TOP_MIN = 0.75

# Below this the flags are still shown but tagged low confidence, because a
# model that cannot learn the task cannot judge its labels either. Both sample
# datasets sit far above it (0.985 and 0.930), so it fires only where the model
# has genuinely failed rather than merely struggled.
WEAK_MODEL_ACCURACY = 0.60
