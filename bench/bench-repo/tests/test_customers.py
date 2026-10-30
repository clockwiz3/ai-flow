from fastapi.testclient import TestClient


def test_list_customers(client: TestClient) -> None:
    body = client.get("/customers").json()
    assert [c["name"] for c in body][:2] == ["Alice Martin", "Bob Chen"]
    assert len(body) == 5


def test_filter_customers_by_tier(client: TestClient) -> None:
    body = client.get("/customers", params={"tier": "gold"}).json()
    assert [c["id"] for c in body] == [3, 5]


def test_create_customer(client: TestClient) -> None:
    response = client.post(
        "/customers", json={"name": "Frank Moore", "email": "Frank@Example.com", "tier": "silver"}
    )
    assert response.status_code == 201
    body = response.json()
    assert body == {"id": 6, "name": "Frank Moore", "email": "frank@example.com", "tier": "silver"}


def test_create_customer_defaults_to_regular(client: TestClient) -> None:
    body = client.post("/customers", json={"name": "Gina", "email": "gina@example.com"}).json()
    assert body["tier"] == "regular"


def test_duplicate_email_rejected(client: TestClient) -> None:
    response = client.post("/customers", json={"name": "A. M.", "email": "ALICE@example.com"})
    assert response.status_code == 409


def test_invalid_email_rejected(client: TestClient) -> None:
    response = client.post("/customers", json={"name": "Nobody", "email": "not-an-email"})
    assert response.status_code == 422


def test_get_customer(client: TestClient) -> None:
    assert client.get("/customers/3").json()["tier"] == "gold"
    assert client.get("/customers/42").status_code == 404
