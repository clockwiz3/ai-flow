from datetime import date

from fastapi.testclient import TestClient

from app.clock import FixedClock

# Seed: reservation 1: item 1, 2025-05-05 .. 2025-05-08, returned 2025-05-07
#       reservation 2: item 5, 2025-05-10 .. 2025-05-17, returned 2025-05-16
#       reservation 3: item 9, 2025-05-20 .. 2025-05-23, cancelled
#       reservation 4: item 2, 2025-06-01 .. 2025-06-04, active
#       reservation 5: item 6, 2025-06-10 .. 2025-06-15, active


def _rows(client: TestClient, start: str, end: str) -> dict[int, dict]:
    response = client.get("/reports/utilization", params={"start": start, "end": end})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["start"] == start and body["end"] == end
    return {row["item_id"]: row for row in body["rows"]}


def _return(client: TestClient, clock: FixedClock, reservation_id: int, on: str) -> None:
    clock.set(date.fromisoformat(on))
    response = client.post(f"/reservations/{reservation_id}/return", json={"returned_on": on})
    assert response.status_code == 200, response.text


def _usage(row: dict) -> tuple[int, int, str]:
    return row["reserved_days"], row["period_days"], row["utilization_pct"]


def test_reservation_started_before_period_is_clipped(client: TestClient) -> None:
    rows = _rows(client, "2025-05-12", "2025-06-01")
    assert rows[5] == {
        "item_id": 5,
        "item_name": "Two-Person Tent",
        "reserved_days": 4,
        "period_days": 20,
        "utilization_pct": "20.0",
    }
    assert _usage(rows[1]) == (0, 20, "0.0")
    assert _usage(rows[9]) == (0, 20, "0.0")
    assert _usage(rows[2]) == (0, 20, "0.0")
    assert len(rows) == 11


def test_early_returns_free_the_rest_of_the_booking(client: TestClient) -> None:
    rows = _rows(client, "2025-05-01", "2025-05-31")
    assert _usage(rows[1]) == (2, 30, "6.7")
    assert _usage(rows[5]) == (6, 30, "20.0")
    assert _usage(rows[9]) == (0, 30, "0.0")


def test_late_return_counts_late_days(client: TestClient, clock: FixedClock) -> None:
    _return(client, clock, 4, "2025-06-06")
    assert _usage(_rows(client, "2025-06-01", "2025-06-11")[2]) == (5, 10, "50.0")
    assert _usage(_rows(client, "2025-06-01", "2025-06-05")[2]) == (4, 4, "100.0")


def test_late_days_after_period_start(client: TestClient, clock: FixedClock) -> None:
    _return(client, clock, 4, "2025-06-06")
    assert _usage(_rows(client, "2025-06-05", "2025-06-10")[2]) == (1, 5, "20.0")
    assert _usage(_rows(client, "2025-06-06", "2025-06-10")[2]) == (0, 4, "0.0")


def test_active_reservation_covering_whole_period(client: TestClient, reserve) -> None:
    reserve(7, 1, "2025-06-02", "2025-06-30")
    assert _usage(_rows(client, "2025-06-10", "2025-06-20")[7]) == (10, 10, "100.0")
    assert _usage(_rows(client, "2025-06-25", "2025-07-05")[7]) == (5, 10, "50.0")
    assert _usage(_rows(client, "2025-06-30", "2025-07-05")[7]) == (0, 5, "0.0")


def test_early_return_spanning_period_start(
    client: TestClient, clock: FixedClock, reserve
) -> None:
    created = reserve(3, 4, "2025-06-02", "2025-06-20")
    _return(client, clock, created["id"], "2025-06-12")
    assert _usage(_rows(client, "2025-06-10", "2025-06-20")[3]) == (2, 10, "20.0")
    assert _usage(_rows(client, "2025-06-12", "2025-06-20")[3]) == (0, 8, "0.0")
    assert _usage(_rows(client, "2025-06-01", "2025-06-30")[3]) == (10, 29, "34.5")


def test_returned_before_period_counts_nothing(
    client: TestClient, clock: FixedClock, reserve
) -> None:
    created = reserve(11, 1, "2025-06-02", "2025-06-16")
    _return(client, clock, created["id"], "2025-06-04")
    assert _usage(_rows(client, "2025-06-05", "2025-06-15")[11]) == (0, 10, "0.0")
    assert _usage(_rows(client, "2025-06-01", "2025-06-15")[11]) == (2, 14, "14.3")


def test_returned_on_start_day_counts_nothing(client: TestClient, reserve) -> None:
    created = reserve(8, 1, "2025-06-02", "2025-06-09")
    assert client.post(f"/reservations/{created['id']}/return").status_code == 200
    assert _usage(_rows(client, "2025-06-01", "2025-06-11")[8]) == (0, 10, "0.0")


def test_several_reservations_of_one_item(
    client: TestClient, clock: FixedClock, reserve
) -> None:
    first = reserve(8, 1, "2025-06-02", "2025-06-05")
    reserve(8, 2, "2025-06-08", "2025-06-12")
    _return(client, clock, first["id"], "2025-06-07")
    assert _usage(_rows(client, "2025-06-04", "2025-06-10")[8]) == (5, 6, "83.3")
    assert _usage(_rows(client, "2025-06-01", "2025-06-15")[8]) == (9, 14, "64.3")


def test_cancelled_reservation_spanning_period_does_not_count(
    client: TestClient, reserve
) -> None:
    created = reserve(9, 1, "2025-06-03", "2025-06-13")
    assert client.post(f"/reservations/{created['id']}/cancel").status_code == 200
    assert _usage(_rows(client, "2025-06-05", "2025-06-10")[9]) == (0, 5, "0.0")


def test_revenue_still_attributed_by_start_date(client: TestClient, reserve) -> None:
    reserve(7, 1, "2025-06-02", "2025-06-30")

    def revenue(start: str, end: str) -> dict:
        response = client.get("/reports/revenue", params={"start": start, "end": end})
        assert response.status_code == 200, response.text
        return response.json()

    body = revenue("2025-06-03", "2025-06-05")
    assert body["rows"] == []
    assert body["total"] == "0.00"

    body = revenue("2025-06-02", "2025-06-03")
    assert body["rows"] == [{"category": "camping", "reservations": 1, "revenue": "192.00"}]
    assert body["total"] == "192.00"

    body = revenue("2025-05-12", "2025-05-20")
    assert body["rows"] == []
