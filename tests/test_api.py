from fastapi.testclient import TestClient

from index import app

client = TestClient(app)


def test_health_reports_the_analytical_stack():
    body = client.get("/api/health").json()
    assert body["ok"] is True
    assert set(body["versions"]) == {"pandas", "numpy", "sklearn"}


def test_routes_are_declared_under_the_api_prefix():
    # vercel.json rewrites /api/(.*) without stripping the prefix, so a route
    # mounted at the bare path would 404 in production and pass locally.
    assert client.get("/health").status_code == 404


def test_profile_returns_types_and_a_preview(churn_csv):
    body = client.post("/api/profile", json={"csv": churn_csv}).json()
    assert body["n_rows"] == 3075
    assert len(body["preview"]) == 20
    types = {c["name"]: c["inferred_type"] for c in body["columns"]}
    assert types["customer_id"] == "id_like"
    assert types["region"] == "constant"


def test_audit_returns_ranked_issues(churn_csv):
    body = client.post(
        "/api/audit", json={"csv": churn_csv, "label_column": "churned", "split_column": "split"}
    ).json()
    assert body["summary"]["medium"] > 0
    assert body["issues"][0]["severity"] in {"high", "medium"}


def test_audit_runs_without_a_label(churn_csv):
    body = client.post("/api/audit", json={"csv": churn_csv}).json()
    assert body["issues"]


def test_oversized_input_is_rejected_with_413(monkeypatch):
    from sift import config

    monkeypatch.setattr(config, "MAX_ROWS", 2)
    response = client.post("/api/profile", json={"csv": "a,b\n1,2\n3,4\n5,6\n"})
    assert response.status_code == 413
    assert "row limit" in response.json()["detail"]


def test_unreadable_input_is_rejected_with_400():
    assert client.post("/api/profile", json={"csv": ""}).status_code == 400


def test_ragged_rows_are_padded_not_rejected():
    # The browser pads short rows and trims long ones before it shows a row
    # count, so a file the user can see on screen must not be refused here.
    body = client.post("/api/audit", json={"csv": "a,b,c\n1,2\n1,2,3,4\n5,6,7\n"})
    assert body.status_code == 200
    profile = client.post("/api/profile", json={"csv": "a,b,c\n1,2\n1,2,3,4\n5,6,7\n"}).json()
    assert profile["n_rows"] == 3
    assert profile["n_cols"] == 3


def test_one_failing_check_does_not_lose_the_whole_audit(churn_csv, monkeypatch):
    from sift.checks import columns as column_checks

    def explode(*args, **kwargs):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(column_checks, "run", explode)
    response = client.post("/api/audit", json={"csv": churn_csv, "label_column": "churned"})

    assert response.status_code == 200, "a broken check should not 500 the request"
    body = response.json()
    # The dataset and row checks still ran and still reported.
    assert body["issues"], "the surviving checks returned nothing"
    reasons = {s["check"]: s["reason"] for s in body["summary"]["skipped_checks"]}
    assert "column checks" in reasons
    assert "RuntimeError" in reasons["column checks"]


def test_an_unexpected_error_returns_a_readable_body(churn_csv, monkeypatch):
    from sift import runner as runner_module

    # This client returns the 500 rather than re-raising, which is what a browser
    # sees. The default one re-raises and the handler never gets to answer.
    forgiving = TestClient(app, raise_server_exceptions=False)
    monkeypatch.setattr(runner_module, "profile_payload", lambda df: 1 / 0)
    response = forgiving.post("/api/profile", json={"csv": churn_csv})
    assert response.status_code == 500
    detail = response.json()["detail"]
    assert "ZeroDivisionError" in detail
    assert "Nothing was stored" in detail


def test_a_file_full_of_awkward_shapes_still_audits():
    cases = [
        "a,a,b\n1,2,3\n4,5,6\n",
        "a,,b\n1,2,3\n4,5,6\n",
        "a\n1\n2\n3\n",
        "a,b\n,\n,\n",
        "a,b,c\n",
        "café,naïve\n1,2\n3,4\n",
        'a,b\n"line\none",2\n"x",3\n',
    ]
    for csv in cases:
        assert client.post("/api/audit", json={"csv": csv}).status_code == 200, csv[:24]


# --- a compressed request body ------------------------------------------------
#
# The platform caps a body at 4.5MB, which is thirty to fifty thousand rows of
# CSV and well under the row limit the checks impose. CSV compresses about five
# to one on real data, so sending it gzipped is the difference between refusing
# a file and auditing it. The browser decides; the server has to accept both.

def test_a_gzipped_body_is_read_the_same_as_a_plain_one(churn_csv):
    import gzip
    import json

    body = json.dumps({"csv": churn_csv}).encode()
    plain = client.post("/api/profile", content=body, headers={"Content-Type": "application/json"})
    packed = client.post(
        "/api/profile",
        content=gzip.compress(body),
        headers={"Content-Type": "application/json", "X-Sift-Compression": "gzip"},
    )
    assert plain.status_code == packed.status_code == 200
    assert plain.json() == packed.json()


def test_the_compression_is_worth_doing(churn_csv):
    import gzip
    import json

    body = json.dumps({"csv": churn_csv}).encode()
    assert len(body) / len(gzip.compress(body)) > 3


def test_a_body_that_is_not_gzip_after_all_says_so():
    response = client.post(
        "/api/profile",
        content=b"this is not gzip",
        headers={"Content-Type": "application/json", "X-Sift-Compression": "gzip"},
    )
    assert response.status_code == 400
    assert "gzip" in response.json()["detail"]


def test_a_malformed_body_is_rejected_rather_than_crashing():
    response = client.post("/api/audit", json={"not_a_field": 1})
    assert response.status_code == 422
