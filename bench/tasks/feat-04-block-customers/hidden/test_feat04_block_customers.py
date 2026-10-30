from fastapi.testclient import TestClient

# Seed customers: 1 Alice (regular), 2 Bob (silver), 3 Carla (gold), 4 Dmitri (regular),
# 5 Emma (gold). Emma has active reservation 5; Dmitri has active reservation 4.


def _book(client: TestClient, customer_id: int, item_id: int = 1):
    payload = {
        "item_id": item_id,
        "customer_id": customer_id,
        "start": "2025-06-05",
        "end": "2025-06-08",
    }
    return client.post("/reservations", json=payload)


def test_customers_expose_blocked_flag(client: TestClient) -> None:
    assert all(c["blocked"] is False for c in client.get("/customers").json())
    assert client.get("/customers/1").json()["blocked"] is False
    created = client.post("/customers", json={"name": "Zoe", "email": "zoe@example.com"})
    assert created.status_code == 201
    assert created.json()["blocked"] is False


def test_block_regular_customer(client: TestClient) -> None:
    response = client.post("/customers/1/block")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == 1
    assert body["blocked"] is True
    assert body["tier"] == "regular"
    assert client.get("/customers/1").json()["blocked"] is True
    listed = {c["id"]: c["blocked"] for c in client.get("/customers").json()}
    assert listed == {1: True, 2: False, 3: False, 4: False, 5: False}


def test_blocked_customer_cannot_reserve(client: TestClient) -> None:
    client.post("/customers/1/block")
    response = _book(client, 1)
    assert response.status_code == 403
    body = response.json()
    assert body["code"] == "forbidden"
    assert "block" in body["detail"].lower()
    assert [r["id"] for r in client.get("/reservations", params={"customer_id": 1}).json()] == [1]


def test_gold_customers_can_be_blocked(client: TestClient) -> None:
    for customer_id in (3, 5):
        response = client.post(f"/customers/{customer_id}/block")
        assert response.status_code == 200
        assert response.json()["blocked"] is True
        assert response.json()["tier"] == "gold"
        assert client.get(f"/customers/{customer_id}").json()["blocked"] is True
        refused = _book(client, customer_id, item_id=customer_id)
        assert refused.status_code == 403, refused.text
        assert refused.json()["code"] == "forbidden"


def test_silver_customer_can_be_blocked(client: TestClient) -> None:
    assert client.post("/customers/2/block").json()["blocked"] is True
    assert _book(client, 2).status_code == 403


def test_unblock_restores_booking(client: TestClient) -> None:
    client.post("/customers/3/block")
    assert _book(client, 3).status_code == 403
    response = client.post("/customers/3/unblock")
    assert response.status_code == 200
    assert response.json()["blocked"] is False
    assert client.get("/customers/3").json()["blocked"] is False
    created = _book(client, 3)
    assert created.status_code == 201, created.text
    assert created.json()["customer_id"] == 3


def test_block_and_unblock_are_idempotent(client: TestClient) -> None:
    assert client.post("/customers/4/unblock").json()["blocked"] is False
    assert client.post("/customers/4/block").json()["blocked"] is True
    second = client.post("/customers/4/block")
    assert second.status_code == 200
    assert second.json()["blocked"] is True


def test_unknown_customer(client: TestClient) -> None:
    for action in ("block", "unblock"):
        response = client.post(f"/customers/42/{action}")
        assert response.status_code == 404
        assert response.json()["code"] == "not_found"
    assert _book(client, 42).status_code == 404


def test_other_customers_unaffected(client: TestClient) -> None:
    client.post("/customers/1/block")
    assert _book(client, 4).status_code == 201


def test_existing_reservations_of_blocked_customer_still_work(client: TestClient) -> None:
    client.post("/customers/5/block")
    assert client.get("/reservations/5").json()["status"] == "active"
    assert client.get("/reservations/5/invoice").status_code == 200
    cancelled = client.post("/reservations/5/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    client.post("/customers/4/block")
    returned = client.post("/reservations/4/return", json={"returned_on": "2025-06-02"})
    assert returned.status_code == 200


def test_blocked_cannot_be_set_on_create(client: TestClient) -> None:
    payload = {"name": "Yan", "email": "yan@example.com", "blocked": True}
    created = client.post("/customers", json=payload)
    # Either the field is ignored or the request is rejected - never a blocked new customer.
    assert created.status_code in (201, 422)
    if created.status_code == 201:
        assert created.json()["blocked"] is False
