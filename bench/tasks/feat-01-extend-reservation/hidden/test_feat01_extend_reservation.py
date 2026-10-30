from decimal import Decimal

from fastapi.testclient import TestClient

# Seed: reservation 4 = Circular Saw (item 2, 18.00/day), regular customer 4,
# 2025-06-01 .. 2025-06-04, active. Today is 2025-06-02.


def _extend(client: TestClient, reservation_id: int, end: str):
    return client.post(f"/reservations/{reservation_id}/extend", json={"end": end})


def test_extend_returns_updated_reservation(client: TestClient) -> None:
    before = client.get("/reservations/4").json()
    response = _extend(client, 4, "2025-06-06")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["end"] == "2025-06-06"
    assert body["status"] == "active"
    for field in ("id", "item_id", "customer_id", "start", "coupon_code", "created_on"):
        assert body[field] == before[field]
    assert client.get("/reservations/4").json() == body


def test_invoice_reflects_new_length(client: TestClient) -> None:
    assert _extend(client, 4, "2025-06-06").status_code == 200
    invoice = client.get("/reservations/4/invoice").json()
    rental = invoice["lines"][0]
    assert rental["quantity"] == 5
    assert Decimal(invoice["subtotal"]) == Decimal("90.00")
    assert Decimal(invoice["tax"]) == Decimal("18.00")
    assert Decimal(invoice["total"]) == Decimal("108.00")


def test_extension_gets_free_day(client: TestClient) -> None:
    # 8 days -> 7 billable
    assert _extend(client, 4, "2025-06-09").status_code == 200
    invoice = client.get("/reservations/4/invoice").json()
    assert invoice["lines"][0]["quantity"] == 7
    assert Decimal(invoice["subtotal"]) == Decimal("126.00")


def test_extend_new_reservation_twice(client: TestClient, reserve) -> None:
    created = reserve(9, 1, "2025-06-05", "2025-06-07")
    assert _extend(client, created["id"], "2025-06-09").status_code == 200
    second = _extend(client, created["id"], "2025-06-12")
    assert second.status_code == 200
    assert second.json()["end"] == "2025-06-12"
    assert second.json()["start"] == "2025-06-05"


def test_unknown_reservation(client: TestClient) -> None:
    response = _extend(client, 404, "2025-06-10")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_cancelled_reservation_cannot_be_extended(client: TestClient) -> None:
    response = _extend(client, 6, "2025-06-20")
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"


def test_returned_reservation_cannot_be_extended(client: TestClient) -> None:
    response = _extend(client, 1, "2025-06-20")
    assert response.status_code == 409


def test_new_end_must_be_after_current_end(client: TestClient) -> None:
    same = _extend(client, 4, "2025-06-04")
    assert same.status_code == 422
    assert same.json()["code"] == "invalid_request"
    earlier = _extend(client, 4, "2025-06-03")
    assert earlier.status_code == 422
    assert client.get("/reservations/4").json()["end"] == "2025-06-04"


def test_ninety_day_limit(client: TestClient) -> None:
    too_long = _extend(client, 4, "2025-08-31")  # 91 days from 2025-06-01
    assert too_long.status_code == 422
    assert client.get("/reservations/4").json()["end"] == "2025-06-04"
    assert _extend(client, 4, "2025-08-30").status_code == 200  # exactly 90 days


def test_conflict_with_next_booking(client: TestClient, reserve) -> None:
    other = reserve(2, 1, "2025-06-06", "2025-06-09")
    response = _extend(client, 4, "2025-06-07")
    assert response.status_code == 409
    assert response.json()["code"] == "conflict"
    assert client.get("/reservations/4").json()["end"] == "2025-06-04"
    assert client.get(f"/reservations/{other['id']}").json()["status"] == "active"


def test_extend_up_to_next_booking_is_allowed(client: TestClient, reserve) -> None:
    reserve(2, 1, "2025-06-06", "2025-06-09")
    response = _extend(client, 4, "2025-06-06")
    assert response.status_code == 200
    assert response.json()["end"] == "2025-06-06"


def test_other_items_bookings_do_not_conflict(client: TestClient, reserve) -> None:
    reserve(3, 1, "2025-06-04", "2025-06-10")
    assert _extend(client, 4, "2025-06-08").status_code == 200


def test_body_validation(client: TestClient) -> None:
    assert client.post("/reservations/4/extend", json={}).status_code == 422
    assert client.post("/reservations/4/extend", json={"end": "soon"}).status_code == 422


def test_extended_reservation_blocks_new_bookings(client: TestClient) -> None:
    assert _extend(client, 4, "2025-06-08").status_code == 200
    payload = {"item_id": 2, "customer_id": 1, "start": "2025-06-06", "end": "2025-06-10"}
    assert client.post("/reservations", json=payload).status_code == 409
