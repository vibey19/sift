# A note on near-duplicates, because I got this wrong first

My first attempt encoded every row into one feature matrix (text through TF-IDF and SVD, numbers rank-scaled, categories one-hot encoded), normalised it, and compared rows by cosine similarity. It returned 27,595 near-duplicate pairs on a dataset where I had planted 20.

The problem is not the threshold. With a handful of one-hot columns, two unrelated rows already sit at a median cosine of 0.51, and the 99th percentile is 0.956. There is no cut point that separates real duplicates from coincidence. Centering the matrix first, which makes cosine behave like a correlation, drops unrelated pairs to a median of −0.03 and still leaves roughly 1,180 false pairs at 0.99.

So I changed the question. A near-duplicate is the same record entered twice: every field agrees except one, and that one is close rather than different. Candidates come from hashing each leave-one-column-out view of the frame, which is linear in the row count instead of quadratic, and the pairwise comparison only ever runs inside a bucket already known to agree on everything else. The single differing field is then judged by its type: a number within tolerance of the column's spread, text above a similarity threshold, anything else equal after normalising case and whitespace.

That took the same dataset from 27,595 pairs to all 20 planted pairs and nothing else.
