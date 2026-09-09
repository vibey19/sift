"""One feature matrix, shared by the near-duplicate, leakage and mislabel checks.

Encoding a dataset three different ways would mean three different answers to
"are these two rows the same", so it is built once here and reused. Identifier,
constant, label and split columns are dropped before encoding: they either carry
no signal or carry the answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import OneHotEncoder, QuantileTransformer

from . import config, profile as prof


@dataclass
class Encoded:
    X: np.ndarray
    columns_used: list[str] = field(default_factory=list)
    text_columns: list[str] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return self.X.size > 0 and self.X.shape[1] > 0


def _svd_components(n_features: int, n_samples: int) -> int:
    # Asking for more components than the matrix has rank returns noise, and a
    # narrow text column can easily have a vocabulary under 128 after min_df.
    return max(1, min(config.SVD_COMPONENTS, n_features - 1, n_samples - 1))


def _encode_text(df: pd.DataFrame, cols: list[str]) -> np.ndarray | None:
    joined = df[cols].fillna("").agg(" ".join, axis=1)
    if joined.str.strip().eq("").all():
        return None
    matrix = TfidfVectorizer(
        ngram_range=config.TFIDF_NGRAM_RANGE,
        max_features=config.TFIDF_MAX_FEATURES,
        min_df=config.TFIDF_MIN_DF,
    ).fit_transform(joined)
    if matrix.shape[1] < 2:
        return None
    n = _svd_components(matrix.shape[1], matrix.shape[0])
    return TruncatedSVD(n_components=n, random_state=0).fit_transform(matrix)


def _encode_numeric(df: pd.DataFrame, cols: list[str], types: dict[str, str]) -> np.ndarray | None:
    frame = {}
    for col in cols:
        if types[col] == prof.DATETIME:
            # Ordinal time is what makes two rows a day apart look close together.
            values = prof.as_datetime(df[col]).reindex(df.index)
            frame[col] = values.astype("int64").where(values.notna()) / 1e9
        else:
            frame[col] = prof.as_numeric(df[col]).reindex(df.index)
    numeric = pd.DataFrame(frame)
    # Median rather than mean, for the same reason C7 uses MAD: the outliers this
    # tool exists to find would otherwise drag every imputed cell with them.
    numeric = numeric.fillna(numeric.median(numeric_only=True))
    numeric = numeric.dropna(axis=1, how="all")
    if numeric.empty or not len(numeric.columns):
        return None
    # Rank-based, so a column with a value at 100x does not dominate the distance.
    return QuantileTransformer(
        n_quantiles=min(1000, max(2, len(numeric))), random_state=0
    ).fit_transform(numeric.to_numpy())


def _encode_categorical(df: pd.DataFrame, cols: list[str]) -> np.ndarray | None:
    values = df[cols].fillna("").astype(str)
    encoded = OneHotEncoder(
        handle_unknown="ignore", min_frequency=0.01, sparse_output=False
    ).fit_transform(values)
    return encoded if encoded.shape[1] else None


def build(
    df: pd.DataFrame,
    profiles: list[dict],
    label_column: str | None = None,
    split_column: str | None = None,
) -> Encoded:
    types = prof.types_by_column(profiles)
    dropped = {label_column, split_column} - {None}

    usable = [
        c for c in df.columns
        if c not in dropped and types[c] not in (prof.ID_LIKE, prof.CONSTANT)
    ]
    if not usable:
        return Encoded(np.empty((len(df), 0)))

    text_cols = [c for c in usable if types[c] == prof.TEXT]
    numeric_cols = [c for c in usable if types[c] in (prof.NUMERIC, prof.DATETIME)]
    cat_cols = [c for c in usable if types[c] in (prof.CATEGORICAL, prof.BOOLEAN)]

    blocks = [
        block for block in (
            _encode_text(df, text_cols) if text_cols else None,
            _encode_numeric(df, numeric_cols, types) if numeric_cols else None,
            _encode_categorical(df, cat_cols) if cat_cols else None,
        ) if block is not None
    ]
    if not blocks:
        return Encoded(np.empty((len(df), 0)))

    return Encoded(
        X=np.hstack(blocks).astype(np.float32),
        columns_used=usable,
        text_columns=text_cols,
    )


def l2_normalise(X: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(X, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return X / norms


def similar_pairs(
    X: np.ndarray,
    threshold: float,
    left_mask: np.ndarray | None = None,
    right_mask: np.ndarray | None = None,
) -> list[tuple[int, int, float]]:
    """Cosine similarity above `threshold`, computed in row blocks.

    The full matrix is n^2 and does not fit in a serverless function past a few
    thousand rows, so it is never materialised. When both masks are given only
    cross-group pairs are returned, which is how D4 asks for train against test.
    """
    V = l2_normalise(X)
    n = len(V)
    cross = left_mask is not None and right_mask is not None
    pairs: list[tuple[int, int, float]] = []

    for start in range(0, n, config.NEAR_DUP_CHUNK):
        stop = min(start + config.NEAR_DUP_CHUNK, n)
        if cross and not left_mask[start:stop].any():
            continue
        sims = V[start:stop] @ V.T

        rows, cols = np.where(sims >= threshold)
        keep = rows + start != cols
        if cross:
            keep &= left_mask[rows + start] & right_mask[cols]
        else:
            # Upper triangle only, or every pair arrives twice.
            keep &= rows + start < cols
        for r, c in zip(rows[keep], cols[keep]):
            pairs.append((int(r + start), int(c), float(sims[r, c])))
    return pairs
