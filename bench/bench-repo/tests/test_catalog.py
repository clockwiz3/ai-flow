from fastapi.testclient import TestClient


def test_health_reports_pinned_date(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "today": "2025-06-02"}


def test_list_categories(client: TestClient) -> None:
    ids = [c["id"] for c in client.get("/categories").json()]
    assert ids == ["camping", "garden", "photo", "tools"]


def test_list_items_default_page(client: TestClient) -> None:
    body = client.get("/items").json()
    assert body["total"] == 12
    assert body["limit"] == 20
    assert body["offset"] == 0
    assert [item["id"] for item in body["items"]] == list(range(1, 13))


def test_list_items_limit(client: TestClient) -> None:
    body = client.get("/items", params={"limit": 5, "offset": 0}).json()
    assert [item["id"] for item in body["items"]] == [1, 2, 3, 4, 5]
    assert body["total"] == 12


def test_list_items_rejects_bad_limit(client: TestClient) -> None:
    assert client.get("/items", params={"limit": 0}).status_code == 422
    assert client.get("/items", params={"limit": 101}).status_code == 422
    assert client.get("/items", params={"offset": -1}).status_code == 422


def test_search_by_name(client: TestClient) -> None:
    body = client.get("/items", params={"q": "Tent"}).json()
    assert [item["name"] for item in body["items"]] == ["Two-Person Tent", "Family Tent"]
    assert body["total"] == 2


def test_search_without_match(client: TestClient) -> None:
    body = client.get("/items", params={"q": "Kayak"}).json()
    assert body == {"items": [], "total": 0, "limit": 20, "offset": 0}


def test_filter_by_category(client: TestClient) -> None:
    body = client.get("/items", params={"category": "camping"}).json()
    assert {item["name"] for item in body["items"]} == {
        "Two-Person Tent",
        "Family Tent",
        "Sleeping Bag",
        "Camping Stove",
    }


def test_search_and_category_combined(client: TestClient) -> None:
    body = client.get("/items", params={"q": "Camera", "category": "photo"}).json()
    assert [item["id"] for item in body["items"]] == [9]


def test_get_item(client: TestClient) -> None:
    body = client.get("/items/1").json()
    assert body == {
        "id": 1,
        "name": "Cordless Drill",
        "category": "tools",
        "daily_rate": "12.00",
        "deposit": "50.00",
        "status": "available",
    }


def test_get_unknown_item(client: TestClient) -> None:
    response = client.get("/items/999")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_create_item(client: TestClient) -> None:
    payload = {"name": "Kayak", "category": "camping", "daily_rate": "40.00", "deposit": "200"}
    response = client.post("/items", json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["id"] == 13
    assert body["status"] == "available"
    assert client.get("/items/13").json()["name"] == "Kayak"


def test_create_item_unknown_category(client: TestClient) -> None:
    payload = {"name": "Kayak", "category": "water", "daily_rate": "40.00", "deposit": "200"}
    assert client.post("/items", json=payload).status_code == 422


def test_create_item_requires_positive_rate(client: TestClient) -> None:
    payload = {"name": "Kayak", "category": "camping", "daily_rate": "0", "deposit": "0"}
    assert client.post("/items", json=payload).status_code == 422


def test_set_item_status(client: TestClient) -> None:
    response = client.post("/items/1/status", json={"status": "maintenance"})
    assert response.status_code == 200
    assert response.json()["status"] == "maintenance"


def test_retired_item_cannot_be_reactivated(client: TestClient) -> None:
    response = client.post("/items/12/status", json={"status": "available"})
    assert response.status_code == 409
