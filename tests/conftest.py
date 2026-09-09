import pytest

from scripts.make_dirty import make_churn, make_reviews


# Session-scoped because generation runs a cross-validated model's worth of work
# and neither frame is mutated by the tests.
@pytest.fixture(scope="session")
def churn():
    return make_churn()


@pytest.fixture(scope="session")
def reviews():
    return make_reviews()


@pytest.fixture(scope="session")
def churn_df(churn):
    return churn[0]


@pytest.fixture(scope="session")
def churn_truth(churn):
    return churn[1]


@pytest.fixture(scope="session")
def reviews_df(reviews):
    return reviews[0]


@pytest.fixture(scope="session")
def reviews_truth(reviews):
    return reviews[1]


def _as_csv(df):
    import io

    buf = io.StringIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


@pytest.fixture(scope="session")
def churn_csv(churn_df):
    return _as_csv(churn_df)


@pytest.fixture(scope="session")
def reviews_csv(reviews_df):
    return _as_csv(reviews_df)


# The checks run against the frame as it arrives from a request, not the one the
# generator held in memory, so anything lost in the CSV round trip shows up here.
@pytest.fixture(scope="session")
def churn_loaded(churn_csv):
    from sift import runner

    return runner.load(churn_csv)


@pytest.fixture(scope="session")
def reviews_loaded(reviews_csv):
    from sift import runner

    return runner.load(reviews_csv)


@pytest.fixture(scope="session")
def churn_issues(churn_loaded):
    from sift import runner

    return runner.audit(churn_loaded, label_column="churned", split_column="split")["issues"]


@pytest.fixture(scope="session")
def reviews_issues(reviews_loaded):
    from sift import runner

    return runner.audit(reviews_loaded, label_column="sentiment", split_column="split")["issues"]


@pytest.fixture
def by_check():
    def pick(issues, check, column=None):
        found = [i for i in issues if i["check"] == check]
        if column is not None:
            found = [i for i in found if i["column"] == column]
        return found

    return pick
