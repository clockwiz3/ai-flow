from fastapi.testclient import TestClient

REASON = "Item is scheduled for maintenance during this period"

# Seed: item 1 Cordless Drill has no upcoming reservations; item 6 Family Tent has active
# reservation 5 (2025-06-10 .. 2025-06-15); item 4 Tile Cutter has status "maintenance".


def _schedule(client: TestClient, item_id: int, start: str, end: str):
    return client.post(f"/items/{item_id}/maintenance", json={"start": start, "end": end})


def _check(client: TestClient, item_id: int, start: str, end: str) -> dict:
    params = {"item_id": item_id, "start": start, "end": end}
    response = client.get("/availability", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_schedule_window(client: TestClient) -> None:
    response = _schedule(client, 1, "2025-06-10", "2025-06-12")
    assert response.status_code == 201, response.text
    body = response.json()
    assert isinstance(body["id"], int) and body["id"] > 0
    assert body["item_id"] == 1
    assert body["start"] == "2025-06-10"
    assert body["end"] == "2025-06-12"
    assert client.get("/items/1").json()["status"] == "available"


def test_list_windows_ordered_by_start(client: TestClient) -> None:
    assert client.get("/items/1/maintenance").json() == []
    late = _schedule(client, 1, "2025-06-20", "2025-06-22").json()
    early = _schedule(client, 1, "2025-06-10", "2025-06-12").json()
    _schedule(client, 3, "2025-06-10", "2025-06-12")
    response = client.get("/items/1/maintenance")
    assert response.status_code == 200
    assert response.json() == [early, late]
    assert late["id"] != early["id"]


def test_unknown_item(client: TestClient) -> None:
    created = _schedule(client, 999, "2025-06-10", "2025-06-12")
    assert created.status_code == 404
    assert created.json()["code"] == "not_found"
    assert client.get("/items/999/maintenance").status_code == 404


def test_invalid_ranges(client: TestClient) -> None:
    empty = _schedule(client, 1, "2025-06-10", "2025-06-10")
    assert empty.status_code == 422
    assert empty.json()["code"] == "invalid_request"
    assert _schedule(client, 1, "2025-06-12", "2025-06-10").status_code == 422
    assert client.post("/items/1/maintenance", json={"start": "2025-06-10"}).status_code == 422
    assert client.get("/items/1/maintenance").json() == []


def test_window_cannot_overlap_active_reservation(client: TestClient) -> None:
    at_end = _schedule(client, 6, "2025-06-14", "2025-06-16")
    assert at_end.status_code == 409
    assert at_end.json()["code"] == "conflict"
    assert _schedule(client, 6, "2025-06-08", "2025-06-11").status_code == 409
    assert _schedule(client, 6, "2025-06-10", "2025-06-15").status_code == 409
    assert client.get("/items/6/maintenance").json() == []


def test_window_back_to_back_with_reservation(client: TestClient) -> None:
    assert _schedule(client, 6, "2025-06-15", "2025-06-17").status_code == 201
    assert _schedule(client, 6, "2025-06-08", "2025-06-10").status_code == 201
    assert len(client.get("/items/6/maintenance").json()) == 2


def test_windows_may_overlap_each_other(client: TestClient) -> None:
    assert _schedule(client, 1, "2025-06-10", "2025-06-14").status_code == 201
    assert _schedule(client, 1, "2025-06-12", "2025-06-16").status_code == 201


def test_availability_blocked_by_window(client: TestClient) -> None:
    _schedule(client, 1, "2025-06-10", "2025-06-12")
    for start, end in [
        ("2025-06-11", "2025-06-13"),
        ("2025-06-09", "2025-06-11"),
        ("2025-06-10", "2025-06-12"),
    ]:
        body = _check(client, 1, start, end)
        assert body["available"] is False, (start, end)
        assert body["reason"] == REASON
        assert body["conflicting_reservation_ids"] == []


def test_availability_around_window(client: TestClient) -> None:
    _schedule(client, 1, "2025-06-10", "2025-06-12")
    assert _check(client, 1, "2025-06-12", "2025-06-14")["available"] is True
    assert _check(client, 1, "2025-06-08", "2025-06-10")["available"] is True
    assert _check(client, 1, "2025-06-20", "2025-06-22")["available"] is True
    assert _check(client, 2, "2025-06-10", "2025-06-12")["available"] is True


def test_reservation_rejected_inside_window(client: TestClient, reserve) -> None:
    _schedule(client, 1, "2025-06-10", "2025-06-12")
    payload = {"item_id": 1, "customer_id": 1, "start": "2025-06-11", "end": "2025-06-13"}
    response = client.post("/reservations", json=payload)
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"
    assert reserve(1, 1, "2025-06-12", "2025-06-14")["status"] == "active"
    assert reserve(1, 2, "2025-06-05", "2025-06-10")["status"] == "active"


def test_window_reason_takes_precedence_over_reservations(client: TestClient) -> None:
    assert _schedule(client, 6, "2025-06-16", "2025-06-18").status_code == 201
    body = _check(client, 6, "2025-06-13", "2025-06-17")
    assert body["available"] is False
    assert body["reason"] == REASON
    assert body["conflicting_reservation_ids"] == [5]


def test_item_status_reason_takes_precedence(client: TestClient) -> None:
    assert _schedule(client, 4, "2025-06-10", "2025-06-12").status_code == 201
    body = _check(client, 4, "2025-06-10", "2025-06-12")
    assert body["available"] is False
    assert body["reason"] == "Item is under maintenance"


def test_utilization_unaffected(client: TestClient) -> None:
    params = {"start": "2025-06-01", "end": "2025-06-11"}
    before = client.get("/reports/utilization", params=params).json()
    assert _schedule(client, 1, "2025-06-03", "2025-06-08").status_code == 201
    assert _schedule(client, 6, "2025-06-04", "2025-06-10").status_code == 201
    after = client.get("/reports/utilization", params=params).json()
    assert after == before
    rows = {row["item_id"]: row for row in after["rows"]}
    assert rows[1]["reserved_days"] == 0
