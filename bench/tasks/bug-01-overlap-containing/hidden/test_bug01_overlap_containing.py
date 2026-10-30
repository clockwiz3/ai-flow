from fastapi.testclient import TestClient


def _availability(client: TestClient, item_id: int, start: str, end: str) -> dict:
    response = client.get(
        "/availability", params={"item_id": item_id, "start": start, "end": end}
    )
    assert response.status_code == 200, response.text
    return response.json()


def _post(client: TestClient, item_id: int, start: str, end: str):
    return client.post(
        "/reservations",
        json={"item_id": item_id, "customer_id": 1, "start": start, "end": end},
    )


def test_containing_range_is_unavailable(client: TestClient) -> None:
    # reservation 5: item 6, 2025-06-10 .. 2025-06-15
    body = _availability(client, 6, "2025-06-09", "2025-06-16")
    assert body["available"] is False
    assert body["reason"]
    assert body["conflicting_reservation_ids"] == [5]


def test_containing_range_reservation_rejected(client: TestClient) -> None:
    response = _post(client, 6, "2025-06-09", "2025-06-16")
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "conflict"
    assert [r["id"] for r in client.get("/reservations", params={"item_id": 6}).json()] == [5]


def test_much_larger_containing_range_rejected(client: TestClient) -> None:
    assert _availability(client, 6, "2025-06-02", "2025-07-01")["available"] is False
    assert _post(client, 6, "2025-06-02", "2025-07-01").status_code == 409


def test_containing_range_of_new_reservation(client: TestClient, reserve) -> None:
    created = reserve(7, 2, "2025-06-20", "2025-06-22")
    body = _availability(client, 7, "2025-06-19", "2025-06-23")
    assert body["available"] is False
    assert body["conflicting_reservation_ids"] == [created["id"]]
    assert _post(client, 7, "2025-06-19", "2025-06-23").status_code == 409


def test_containing_range_spanning_two_reservations(client: TestClient, reserve) -> None:
    first = reserve(8, 2, "2025-06-10", "2025-06-12")
    second = reserve(8, 3, "2025-06-14", "2025-06-16")
    body = _availability(client, 8, "2025-06-09", "2025-06-17")
    assert body["available"] is False
    assert sorted(body["conflicting_reservation_ids"]) == sorted([first["id"], second["id"]])


def test_other_overlaps_still_detected(client: TestClient) -> None:
    for start, end in [
        ("2025-06-09", "2025-06-11"),  # ends inside
        ("2025-06-14", "2025-06-20"),  # starts inside
        ("2025-06-11", "2025-06-13"),  # inside
        ("2025-06-10", "2025-06-15"),  # identical
    ]:
        body = _availability(client, 6, start, end)
        assert body["available"] is False, (start, end)
        assert body["conflicting_reservation_ids"] == [5], (start, end)


def test_touching_ranges_still_allowed(client: TestClient) -> None:
    assert _availability(client, 6, "2025-06-05", "2025-06-10")["available"] is True
    assert _availability(client, 6, "2025-06-15", "2025-06-20")["available"] is True
    assert _post(client, 6, "2025-06-05", "2025-06-10").status_code == 201
    assert _post(client, 6, "2025-06-15", "2025-06-20").status_code == 201
