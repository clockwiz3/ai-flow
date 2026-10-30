from fastapi.testclient import TestClient


def _revenue(client: TestClient, start: str, end: str) -> dict:
    response = client.get("/reports/revenue", params={"start": start, "end": end})
    assert response.status_code == 200, response.text
    return response.json()


def test_seeded_cancelled_reservations_excluded(client: TestClient) -> None:
    body = _revenue(client, "2025-05-01", "2025-06-10")
    assert body["rows"] == [
        {"category": "camping", "reservations": 1, "revenue": "102.00"},
        {"category": "tools", "reservations": 2, "revenue": "90.00"},
    ]
    assert body["total"] == "192.00"


def test_period_with_only_cancelled_reservations_is_empty(client: TestClient) -> None:
    # reservation 3 (photo, 2025-05-20) is cancelled
    body = _revenue(client, "2025-05-18", "2025-05-25")
    assert body["rows"] == []
    assert body["total"] == "0.00"


def test_reservation_cancelled_via_api_is_excluded(client: TestClient, reserve) -> None:
    kept = reserve(7, 1, "2025-06-20", "2025-06-22")  # Sleeping Bag 8.00/day -> 16.00
    dropped = reserve(9, 1, "2025-06-20", "2025-06-23")  # camera, will be cancelled
    assert client.post(f"/reservations/{dropped['id']}/cancel").status_code == 200

    body = _revenue(client, "2025-06-20", "2025-06-21")
    assert body["rows"] == [{"category": "camping", "reservations": 1, "revenue": "16.00"}]
    assert body["total"] == "16.00"
    assert kept["status"] == "active"


def test_active_and_returned_still_counted(client: TestClient) -> None:
    assert client.post("/reservations/4/return").status_code == 200  # tools, 54.00
    body = _revenue(client, "2025-05-01", "2025-06-20")
    rows = {row["category"]: row for row in body["rows"]}
    assert rows["tools"] == {"category": "tools", "reservations": 2, "revenue": "90.00"}
    # reservation 2 (returned, 102.00) + reservation 5 (active, gold, Family Tent 5 days)
    assert rows["camping"] == {"category": "camping", "reservations": 2, "revenue": "250.75"}
    assert "photo" not in rows
    assert body["total"] == "340.75"


def test_utilization_unchanged(client: TestClient) -> None:
    body = client.get(
        "/reports/utilization", params={"start": "2025-06-01", "end": "2025-06-11"}
    ).json()
    rows = {row["item_id"]: row for row in body["rows"]}
    assert rows[10]["reserved_days"] == 0
    assert rows[2]["reserved_days"] == 3
