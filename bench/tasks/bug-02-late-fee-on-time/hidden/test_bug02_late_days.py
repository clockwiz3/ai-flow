from datetime import date

from fastapi.testclient import TestClient

from app.clock import FixedClock

# reservation 4: item 2 (Circular Saw, 18.00/day), 2025-06-01 .. 2025-06-04, regular customer


def _return(client: TestClient, clock: FixedClock, on: str) -> dict:
    clock.set(date.fromisoformat(on))
    response = client.post("/reservations/4/return", json={"returned_on": on})
    assert response.status_code == 200, response.text
    return response.json()


def test_return_on_end_date_is_on_time(client: TestClient, clock: FixedClock) -> None:
    receipt = _return(client, clock, "2025-06-04")
    assert receipt["late_days"] == 0
    assert receipt["late_fee"] == "0.00"


def test_invoice_after_on_time_return_has_no_late_fee(
    client: TestClient, clock: FixedClock
) -> None:
    _return(client, clock, "2025-06-04")
    invoice = client.get("/reservations/4/invoice").json()
    assert [line["kind"] for line in invoice["lines"]] == ["rental"]
    assert invoice["subtotal"] == "54.00"
    assert invoice["tax"] == "10.80"
    assert invoice["total"] == "64.80"


def test_one_day_late(client: TestClient, clock: FixedClock) -> None:
    receipt = _return(client, clock, "2025-06-05")
    assert receipt["late_days"] == 1
    assert receipt["late_fee"] == "27.00"
    invoice = client.get("/reservations/4/invoice").json()
    late = [line for line in invoice["lines"] if line["kind"] == "late_fee"]
    assert len(late) == 1
    assert late[0]["quantity"] == 1
    assert late[0]["amount"] == "27.00"


def test_several_days_late(client: TestClient, clock: FixedClock) -> None:
    receipt = _return(client, clock, "2025-06-06")
    assert receipt["late_days"] == 2
    assert receipt["late_fee"] == "54.00"
    invoice = client.get("/reservations/4/invoice").json()
    late = [line for line in invoice["lines"] if line["kind"] == "late_fee"]
    assert late[0]["quantity"] == 2
    assert late[0]["amount"] == "54.00"
    assert invoice["subtotal"] == "108.00"
    assert invoice["tax"] == "21.60"
    assert invoice["total"] == "129.60"


def test_early_return_still_free(client: TestClient, clock: FixedClock) -> None:
    receipt = _return(client, clock, "2025-06-02")
    assert receipt["late_days"] == 0
    assert receipt["late_fee"] == "0.00"
    invoice = client.get("/reservations/4/invoice").json()
    assert [line["kind"] for line in invoice["lines"]] == ["rental"]
    assert invoice["total"] == "64.80"


def test_default_return_date_uses_today(client: TestClient, clock: FixedClock) -> None:
    clock.set(date(2025, 6, 7))
    receipt = client.post("/reservations/4/return").json()
    assert receipt["returned_on"] == "2025-06-07"
    assert receipt["late_days"] == 3
    assert receipt["late_fee"] == "81.00"
