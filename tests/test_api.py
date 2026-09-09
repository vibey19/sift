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
