from decimal import Decimal

from fastapi.testclient import TestClient

from app.clock import FixedClock

# Today (test clock) is 2025-06-02.


def _coupon(client: TestClient, code: str, percent: int, expires_on: str | None = None):
    payload: dict = {"code": code, "percent": percent}
    if expires_on is not None:
        payload["expires_on"] = expires_on
    return client.post("/coupons", json=payload)


def _book(client: TestClient, code: str, start: str = "2025-06-05", end: str = "2025-06-08"):
    payload = {"item_id": 1, "customer_id": 1, "start": start, "end": end, "coupon_code": code}
    return client.post("/reservations", json=payload)


def test_create_coupon_with_expiry(client: TestClient) -> None:
    response = _coupon(client, "summer15", 15, "2025-08-31")
    assert response.status_code == 201, response.text
    assert response.json() == {"code": "SUMMER15", "percent": 15, "expires_on": "2025-08-31"}
    listed = {c["code"]: c for c in client.get("/coupons").json()}
    assert listed["SUMMER15"]["expires_on"] == "2025-08-31"


def test_coupons_without_expiry(client: TestClient) -> None:
    created = _coupon(client, "FOREVER5", 5)
    assert created.status_code == 201
    assert created.json()["expires_on"] is None
    payload = {"code": "NULL5", "percent": 5, "expires_on": None}
    explicit_null = client.post("/coupons", json=payload)
    assert explicit_null.status_code == 201
    assert explicit_null.json()["expires_on"] is None
    listed = {c["code"]: c["expires_on"] for c in client.get("/coupons").json()}
    assert listed["SPRING10"] is None
    assert listed["WELCOME20"] is None


def test_malformed_expiry_rejected(client: TestClient) -> None:
    assert _coupon(client, "BADDATE", 5, "next-week").status_code == 422


def test_past_expiry_can_be_created(client: TestClient) -> None:
    assert _coupon(client, "OLD10", 10, "2025-01-31").status_code == 201


def test_expired_coupon_rejected(client: TestClient) -> None:
    _coupon(client, "MAY10", 10, "2025-06-01")
    response = _book(client, "MAY10")
    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "invalid_request"
    assert "expired" in body["detail"].lower()
    assert client.get("/reservations", params={"customer_id": 1}).json()[-1]["id"] == 1


def test_expired_coupon_code_is_case_insensitive(client: TestClient) -> None:
    _coupon(client, "MAY10", 10, "2025-06-01")
    response = _book(client, "may10")
    assert response.status_code == 422
    assert "expired" in response.json()["detail"].lower()


def test_coupon_valid_on_its_expiry_day(client: TestClient) -> None:
    _coupon(client, "TODAY10", 10, "2025-06-02")
    response = _book(client, "TODAY10")
    assert response.status_code == 201, response.text
    assert response.json()["coupon_code"] == "TODAY10"


def test_expiry_follows_the_clock(client: TestClient, clock: FixedClock) -> None:
    _coupon(client, "JUNE10", 10, "2025-06-03")
    assert _book(client, "JUNE10", "2025-06-05", "2025-06-06").status_code == 201
    clock.set(clock.today().replace(day=3))
    assert _book(client, "JUNE10", "2025-06-06", "2025-06-07").status_code == 201
    clock.advance()
    response = _book(client, "JUNE10", "2025-06-07", "2025-06-08")
    assert response.status_code == 422
    assert "expired" in response.json()["detail"].lower()


def test_expiry_compared_to_today_not_start(client: TestClient) -> None:
    _coupon(client, "EARLY10", 10, "2025-06-30")
    response = _book(client, "EARLY10", "2025-07-01", "2025-07-04")
    assert response.status_code == 201, response.text


def test_seed_coupons_still_work(client: TestClient) -> None:
    response = _book(client, "SPRING10")
    assert response.status_code == 201
    assert response.json()["coupon_code"] == "SPRING10"


def test_unknown_coupon_still_rejected(client: TestClient) -> None:
    assert _book(client, "NOPE").status_code == 422


def test_existing_reservation_keeps_discount_after_expiry(
    client: TestClient, clock: FixedClock
) -> None:
    _coupon(client, "SHORT10", 10, "2025-06-02")
    created = _book(client, "SHORT10")
    assert created.status_code == 201
    clock.advance(5)
    invoice = client.get(f"/reservations/{created.json()['id']}/invoice")
    assert invoice.status_code == 200
    assert Decimal(invoice.json()["discount"]) > 0
    assert client.get(f"/reservations/{created.json()['id']}").json()["coupon_code"] == "SHORT10"
