from fastapi.testclient import TestClient


def _payload(item_id: int, customer_id: int, start: str, end: str, **extra: object) -> dict:
    return {"item_id": item_id, "customer_id": customer_id, "start": start, "end": end, **extra}


def test_create_reservation(client: TestClient, reserve) -> None:
    body = reserve(1, 1, "2025-06-05", "2025-06-08")
    assert body["id"] == 7
    assert body["status"] == "active"
    assert body["created_on"] == "2025-06-02"
    assert body["coupon_code"] is None
    assert client.get("/reservations/7").json() == body


def test_reservation_starting_today_is_allowed(reserve) -> None:
    assert reserve(3, 1, "2025-06-02", "2025-06-03")["status"] == "active"


def test_reservation_in_the_past_rejected(client: TestClient) -> None:
    response = client.post("/reservations", json=_payload(1, 1, "2025-06-01", "2025-06-04"))
    assert response.status_code == 422


def test_empty_range_rejected(client: TestClient) -> None:
    response = client.post("/reservations", json=_payload(1, 1, "2025-06-05", "2025-06-05"))
    assert response.status_code == 422


def test_too_long_reservation_rejected(client: TestClient) -> None:
    response = client.post("/reservations", json=_payload(1, 1, "2025-06-05", "2025-09-05"))
    assert response.status_code == 422


def test_overlapping_reservation_rejected(client: TestClient) -> None:
    # reservation 4 holds the circular saw from 2025-06-01 to 2025-06-04
    response = client.post("/reservations", json=_payload(2, 1, "2025-06-03", "2025-06-06"))
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


def test_back_to_back_reservation_allowed(reserve) -> None:
    body = reserve(2, 1, "2025-06-04", "2025-06-06")
    assert body["start"] == "2025-06-04"


def test_item_in_maintenance_cannot_be_reserved(client: TestClient) -> None:
    response = client.post("/reservations", json=_payload(4, 1, "2025-06-05", "2025-06-06"))
    assert response.status_code == 409


def test_retired_item_cannot_be_reserved(client: TestClient) -> None:
    response = client.post("/reservations", json=_payload(12, 1, "2025-06-05", "2025-06-06"))
    assert response.status_code == 409


def test_unknown_item_or_customer(client: TestClient) -> None:
    unknown_item = _payload(99, 1, "2025-06-05", "2025-06-06")
    unknown_customer = _payload(1, 99, "2025-06-05", "2025-06-06")
    assert client.post("/reservations", json=unknown_item).status_code == 404
    assert client.post("/reservations", json=unknown_customer).status_code == 404


def test_coupon_code_is_normalised(reserve) -> None:
    body = reserve(1, 1, "2025-06-05", "2025-06-08", coupon_code="spring10")
    assert body["coupon_code"] == "SPRING10"


def test_unknown_coupon_rejected(client: TestClient) -> None:
    payload = _payload(1, 1, "2025-06-05", "2025-06-08", coupon_code="NOPE")
    assert client.post("/reservations", json=payload).status_code == 422


def test_cancel_reservation(client: TestClient) -> None:
    response = client.post("/reservations/5/cancel")
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    assert client.get("/reservations/5").json()["status"] == "cancelled"


def test_cancel_twice_conflicts(client: TestClient) -> None:
    assert client.post("/reservations/5/cancel").status_code == 200
    assert client.post("/reservations/5/cancel").status_code == 409


def test_returned_reservation_cannot_be_cancelled(client: TestClient) -> None:
    assert client.post("/reservations/1/cancel").status_code == 409


def test_list_reservations_filters(client: TestClient) -> None:
    by_customer = client.get("/reservations", params={"customer_id": 2}).json()
    assert [r["id"] for r in by_customer] == [3, 6]
    active = client.get("/reservations", params={"status": "active"}).json()
    assert [r["id"] for r in active] == [4, 5]
    by_item = client.get("/reservations", params={"item_id": 5}).json()
    assert [r["id"] for r in by_item] == [2]


def test_unknown_reservation(client: TestClient) -> None:
    assert client.get("/reservations/404").status_code == 404
    assert client.post("/reservations/404/cancel").status_code == 404
