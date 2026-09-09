from . import config

HIGH = "high"
MEDIUM = "medium"
LOW = "low"

_ORDER = {HIGH: 0, MEDIUM: 1, LOW: 2}


def make_issue(
    *,
    id: str,
    check: str,
    scope: str,
    severity: str,
    title: str,
    detail: str,
    column: str | None = None,
    row_indices=(),
    total_affected: int | None = None,
    suggested_action: str = "review",
    evidence: dict | None = None,
) -> dict:
    rows = [int(i) for i in row_indices]
    return {
        "id": id,
        "check": check,
        "scope": scope,
        "severity": severity,
        "title": title,
        "detail": detail,
        "column": column,
        # The full list can be tens of thousands of rows; the UI only ever needs
        # enough to page through, and total_affected keeps the count honest.
        "row_indices": rows[: config.MAX_ROW_INDICES],
        "total_affected": len(rows) if total_affected is None else int(total_affected),
        "suggested_action": suggested_action,
        "evidence": evidence or {},
    }


def sort_issues(issues: list[dict]) -> list[dict]:
    return sorted(issues, key=lambda i: (_ORDER[i["severity"]], -i["total_affected"]))


def pct(x: float) -> str:
    # Whole numbers below 1% read as "0%", which looks like a bug in the UI.
    return f"{x * 100:.1f}%" if x < 0.1 else f"{x * 100:.0f}%"
