from fastapi.testclient import TestClient


def _check(client: TestClient, item_id: int, start: str, end: str) -> dict:
    response = client.get("/availability", params={"item_id": item_id, "start": start, "end": end})
    assert response.status_code == 200, response.text
    return response.json()


def test_free_item_is_available(client: TestClient) -> None:
    body = _check(client, 1, "2025-06-05", "2025-06-08")
    assert body == {
        "item_id": 1,
        "start": "2025-06-05",
        "end": "2025-06-08",
        "available": True,
        "reason": None,
        "conflicting_reservation_ids": [],
    }


def test_overlap_at_start_of_existing(client: TestClient) -> None:
    # reservation 5: family tent 2025-06-10 .. 2025-06-15
    body = _check(client, 6, "2025-06-08", "2025-06-11")
    assert body["available"] is False
    assert body["conflicting_reservation_ids"] == [5]


def test_overlap_at_end_of_existing(client: TestClient) -> None:
    body = _check(client, 6, "2025-06-14", "2025-06-18")
    assert body["available"] is False
    assert body["conflicting_reservation_ids"] == [5]


def test_identical_range_conflicts(client: TestClient) -> None:
    body = _check(client, 6, "2025-06-10", "2025-06-15")
    assert body["conflicting_reservation_ids"] == [5]


def test_back_to_back_ranges_are_available(client: TestClient) -> None:
    assert _check(client, 6, "2025-06-15", "2025-06-17")["available"] is True
    assert _check(client, 6, "2025-06-07", "2025-06-10")["available"] is True


def test_maintenance_item_is_unavailable(client: TestClient) -> None:
    body = _check(client, 4, "2025-06-05", "2025-06-06")
    assert body["available"] is False
    assert body["reason"] == "Item is under maintenance"


def test_retired_item_is_unavailable(client: TestClient) -> None:
    body = _check(client, 12, "2025-06-05", "2025-06-06")
    assert body["available"] is False
    assert body["reason"] == "Item is retired"


def test_new_reservation_blocks_availability(client: TestClient, reserve) -> None:
    created = reserve(3, 2, "2025-06-20", "2025-06-25")
    body = _check(client, 3, "2025-06-22", "2025-06-27")
    assert body["conflicting_reservation_ids"] == [created["id"]]


def test_returned_reservation_does_not_block(client: TestClient) -> None:
    # reservation 1 (returned) covered 2025-05-05 .. 2025-05-08 for the drill
    assert _check(client, 1, "2025-05-06", "2025-05-09")["available"] is True


def test_invalid_range(client: TestClient) -> None:
    params = {"item_id": 1, "start": "2025-06-08", "end": "2025-06-05"}
    assert client.get("/availability", params=params).status_code == 422


def test_unknown_item(client: TestClient) -> None:
    params = {"item_id": 77, "start": "2025-06-05", "end": "2025-06-08"}
    assert client.get("/availability", params=params).status_code == 404
