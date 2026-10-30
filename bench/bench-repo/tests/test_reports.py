from fastapi.testclient import TestClient


def test_revenue_by_category(client: TestClient) -> None:
    response = client.get("/reports/revenue", params={"start": "2025-05-01", "end": "2025-05-20"})
    assert response.status_code == 200
    assert response.json() == {
        "start": "2025-05-01",
        "end": "2025-05-20",
        "rows": [
            {"category": "camping", "reservations": 1, "revenue": "102.00"},
            {"category": "tools", "reservations": 1, "revenue": "36.00"},
        ],
        "total": "138.00",
    }


def test_revenue_counts_active_reservations(client: TestClient) -> None:
    params = {"start": "2025-06-01", "end": "2025-06-05"}
    body = client.get("/reports/revenue", params=params).json()
    assert body["rows"] == [{"category": "tools", "reservations": 1, "revenue": "54.00"}]
    assert body["total"] == "54.00"


def test_revenue_empty_period(client: TestClient) -> None:
    params = {"start": "2025-01-01", "end": "2025-02-01"}
    body = client.get("/reports/revenue", params=params).json()
    assert body["rows"] == []
    assert body["total"] == "0.00"


def test_revenue_invalid_range(client: TestClient) -> None:
    params = {"start": "2025-06-01", "end": "2025-06-01"}
    assert client.get("/reports/revenue", params=params).status_code == 422


def test_utilization(client: TestClient) -> None:
    params = {"start": "2025-06-01", "end": "2025-06-11"}
    body = client.get("/reports/utilization", params=params).json()
    rows = {row["item_id"]: row for row in body["rows"]}
    assert rows[2] == {
        "item_id": 2,
        "item_name": "Circular Saw",
        "reserved_days": 3,
        "period_days": 10,
        "utilization_pct": "30.0",
    }
    assert rows[6]["utilization_pct"] == "10.0"
    assert rows[1]["utilization_pct"] == "0.0"
    assert rows[10]["reserved_days"] == 0


def test_utilization_skips_retired_items(client: TestClient) -> None:
    params = {"start": "2025-06-01", "end": "2025-06-11"}
    body = client.get("/reports/utilization", params=params).json()
    assert 12 not in [row["item_id"] for row in body["rows"]]
    assert len(body["rows"]) == 11


def test_utilization_includes_new_reservations(client: TestClient, reserve) -> None:
    reserve(9, 1, "2025-06-03", "2025-06-06")
    params = {"start": "2025-06-01", "end": "2025-06-11"}
    rows = client.get("/reports/utilization", params=params).json()["rows"]
    camera = next(row for row in rows if row["item_id"] == 9)
    assert camera["reserved_days"] == 3
    assert camera["utilization_pct"] == "30.0"
