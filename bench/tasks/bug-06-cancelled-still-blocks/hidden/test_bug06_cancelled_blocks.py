from fastapi.testclient import TestClient


def _availability(client: TestClient, item_id: int, start: str, end: str) -> dict:
    response = client.get(
        "/availability", params={"item_id": item_id, "start": start, "end": end}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _post(client: TestClient, item_id: int, customer_id: int, start: str, end: str):
    return client.post(
        "/reservations",
        json={"item_id": item_id, "customer_id": customer_id, "start": start, "end": end},
    )


def test_seeded_cancelled_reservation_does_not_block(client: TestClient) -> None:
    # reservation 6: item 10, 2025-06-05 .. 2025-06-08, cancelled
    body = _availability(client, 10, "2025-06-05", "2025-06-08")
    assert body["available"] is True
    assert body["reason"] is None
    assert body["conflicting_reservation_ids"] == []


def test_can_book_over_seeded_cancelled_reservation(client: TestClient) -> None:
    response = _post(client, 10, 1, "2025-06-05", "2025-06-08")
    assert response.status_code == 201, response.text
    assert _post(client, 10, 3, "2025-06-06", "2025-06-07").status_code == 409


def test_cancelling_frees_the_dates(client: TestClient, reserve) -> None:
    created = reserve(7, 1, "2025-06-20", "2025-06-25")
    assert _availability(client, 7, "2025-06-21", "2025-06-23")["available"] is False

    assert client.post(f"/reservations/{created['id']}/cancel").status_code == 200

    body = _availability(client, 7, "2025-06-21", "2025-06-23")
    assert body["available"] is True
    assert body["conflicting_reservation_ids"] == []
    assert _post(client, 7, 2, "2025-06-20", "2025-06-25").status_code == 201


def test_cancelled_ignored_but_active_still_reported(client: TestClient, reserve) -> None:
    cancelled = reserve(8, 1, "2025-06-20", "2025-06-22")
    client.post(f"/reservations/{cancelled['id']}/cancel")
    active = reserve(8, 2, "2025-06-20", "2025-06-22")
    body = _availability(client, 8, "2025-06-21", "2025-06-22")
    assert body["available"] is False
    assert body["conflicting_reservation_ids"] == [active["id"]]


def test_active_reservations_still_block(client: TestClient) -> None:
    # reservation 5: item 6, 2025-06-10 .. 2025-06-15, active
    body = _availability(client, 6, "2025-06-12", "2025-06-14")
    assert body["available"] is False
    assert body["conflicting_reservation_ids"] == [5]
    assert _post(client, 6, 1, "2025-06-12", "2025-06-14").status_code == 409


def test_returned_reservations_still_do_not_block(client: TestClient) -> None:
    # reservation 4: item 2, 2025-06-01 .. 2025-06-04, returned early today
    assert client.post("/reservations/4/return").status_code == 200
    assert _availability(client, 2, "2025-06-02", "2025-06-04")["available"] is True
    assert _post(client, 2, 1, "2025-06-02", "2025-06-04").status_code == 201
