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
