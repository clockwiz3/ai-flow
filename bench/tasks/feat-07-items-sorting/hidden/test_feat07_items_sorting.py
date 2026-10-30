from fastapi.testclient import TestClient

# Seed items (id: name, daily rate):
#  1 Cordless Drill 12.00     2 Circular Saw 18.00     3 Rotary Hammer 25.00
#  4 Tile Cutter 15.00        5 Two-Person Tent 20.00  6 Family Tent 35.00
#  7 Sleeping Bag 8.00        8 Camping Stove 6.50     9 Mirrorless Camera 45.00
# 10 Telephoto Lens 30.00    11 Hedge Trimmer 14.00   12 Lawn Aerator 16.00

BY_NAME = [8, 2, 1, 6, 11, 12, 9, 3, 7, 10, 4, 5]
BY_RATE = [8, 7, 1, 11, 4, 12, 2, 5, 3, 10, 6, 9]


def _ids(client: TestClient, **params: object) -> list[int]:
    response = client.get("/items", params={"offset": 0, **params})
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["items"]]


def test_default_order_unchanged(client: TestClient) -> None:
    assert _ids(client) == list(range(1, 13))
    assert _ids(client, sort="id", order="asc") == list(range(1, 13))


def test_sort_by_name(client: TestClient) -> None:
    assert _ids(client, sort="name") == BY_NAME
    assert _ids(client, sort="name", order="asc") == BY_NAME
    assert _ids(client, sort="name", order="desc") == list(reversed(BY_NAME))


def test_sort_by_daily_rate_is_numeric(client: TestClient) -> None:
    assert _ids(client, sort="daily_rate") == BY_RATE
    assert _ids(client, sort="daily_rate", order="desc") == list(reversed(BY_RATE))


def test_desc_without_sort_uses_id(client: TestClient) -> None:
    assert _ids(client, order="desc") == list(range(12, 0, -1))


def test_sort_before_pagination(client: TestClient) -> None:
    response = client.get(
        "/items", params={"sort": "daily_rate", "order": "desc", "limit": 3, "offset": 0}
    )
    body = response.json()
    assert [item["id"] for item in body["items"]] == [9, 6, 10]
    assert body["total"] == 12
    assert body["limit"] == 3


def test_sort_with_category_filter(client: TestClient) -> None:
    assert _ids(client, category="camping", sort="name") == [8, 6, 7, 5]
    assert _ids(client, category="camping", sort="daily_rate", order="desc") == [6, 5, 7, 8]


def test_sort_with_search(client: TestClient) -> None:
    response = client.get("/items", params={"q": "Tent", "sort": "daily_rate", "order": "desc"})
    body = response.json()
    assert [item["id"] for item in body["items"]] == [6, 5]
    assert body["total"] == 2
    assert _ids(client, q="Tent", sort="name") == [6, 5]


def test_name_sort_is_case_insensitive(client: TestClient) -> None:
    payload = {"name": "anvil", "category": "tools", "daily_rate": "9.00", "deposit": "20"}
    created = client.post("/items", json=payload).json()
    assert _ids(client, sort="name")[0] == created["id"]
    assert _ids(client, sort="name", order="desc")[-1] == created["id"]


def test_ties_broken_by_id_ascending(client: TestClient) -> None:
    payload = {"name": "Bench Grinder", "category": "tools", "daily_rate": "12.00", "deposit": "40"}
    created = client.post("/items", json=payload).json()
    new_id = created["id"]
    assert _ids(client, category="tools", sort="daily_rate") == [1, new_id, 4, 2, 3]
    assert _ids(client, category="tools", sort="daily_rate", order="desc") == [3, 2, 4, 1, new_id]


def test_invalid_values_rejected(client: TestClient) -> None:
    assert client.get("/items", params={"sort": "price"}).status_code == 422
    assert client.get("/items", params={"order": "up"}).status_code == 422
    assert client.get("/items", params={"sort": "name", "order": "sideways"}).status_code == 422
