from datetime import date

from fastapi.testclient import TestClient

from app.clock import FixedClock


def test_early_return_refunds_deposit(client: TestClient) -> None:
    # reservation 4: circular saw 2025-06-01 .. 2025-06-04, deposit 80.00
    response = client.post("/reservations/4/return", json={"returned_on": "2025-06-02"})
    assert response.status_code == 200
    assert response.json() == {
        "reservation_id": 4,
        "returned_on": "2025-06-02",
        "late_days": 0,
        "late_fee": "0.00",
        "damaged": False,
        "deposit": "80.00",
        "deposit_refunded": "80.00",
        "deposit_withheld": "0.00",
    }
    reservation = client.get("/reservations/4").json()
    assert reservation["status"] == "returned"
    assert reservation["returned_on"] == "2025-06-02"


def test_return_date_defaults_to_today(client: TestClient) -> None:
    body = client.post("/reservations/4/return").json()
    assert body["returned_on"] == "2025-06-02"


def test_damaged_return_withholds_deposit(client: TestClient) -> None:
    body = client.post("/reservations/4/return", json={"damaged": True}).json()
    assert body["deposit_refunded"] == "0.00"
    assert body["deposit_withheld"] == "80.00"
    assert client.get("/items/2").json()["status"] == "maintenance"
    assert client.get("/reservations/4").json()["damaged"] is True


def test_undamaged_return_keeps_item_available(client: TestClient) -> None:
    client.post("/reservations/4/return", json={"damaged": False})
    assert client.get("/items/2").json()["status"] == "available"


def test_late_return_adds_late_fee_line(client: TestClient, clock: FixedClock) -> None:
    clock.set(date(2025, 6, 9))
    receipt = client.post("/reservations/4/return").json()
    assert receipt["late_days"] > 0
    invoice = client.get("/reservations/4/invoice").json()
    assert [line["kind"] for line in invoice["lines"]] == ["rental", "late_fee"]


def test_return_in_future_rejected(client: TestClient) -> None:
    response = client.post("/reservations/4/return", json={"returned_on": "2025-06-03"})
    assert response.status_code == 422


def test_return_before_start_rejected(client: TestClient) -> None:
    response = client.post("/reservations/4/return", json={"returned_on": "2025-05-31"})
    assert response.status_code == 422


def test_cannot_return_twice(client: TestClient) -> None:
    assert client.post("/reservations/4/return").status_code == 200
    assert client.post("/reservations/4/return").status_code == 409


def test_cannot_return_cancelled(client: TestClient) -> None:
    assert client.post("/reservations/3/return").status_code == 409
