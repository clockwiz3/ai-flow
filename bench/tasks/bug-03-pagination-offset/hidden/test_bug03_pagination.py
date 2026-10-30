from fastapi.testclient import TestClient


def _page(client: TestClient, **params) -> dict:
    response = client.get("/items", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _ids(body: dict) -> list[int]:
    return [item["id"] for item in body["items"]]


def test_second_page(client: TestClient) -> None:
    body = _page(client, limit=5, offset=5)
    assert _ids(body) == [6, 7, 8, 9, 10]
    assert body["total"] == 12
    assert body["limit"] == 5
    assert body["offset"] == 5


def test_offset_smaller_than_limit(client: TestClient) -> None:
    assert _ids(_page(client, limit=3, offset=2)) == [3, 4, 5]


def test_last_partial_page(client: TestClient) -> None:
    body = _page(client, limit=5, offset=10)
    assert _ids(body) == [11, 12]
    assert body["total"] == 12


def test_pages_cover_catalog_without_gaps(client: TestClient) -> None:
    seen: list[int] = []
    for offset in range(0, 12, 4):
        seen += _ids(_page(client, limit=4, offset=offset))
    assert seen == list(range(1, 13))


def test_offset_past_end_is_empty(client: TestClient) -> None:
    body = _page(client, limit=5, offset=12)
    assert body["items"] == []
    assert body["total"] == 12
    assert _page(client, limit=5, offset=50)["items"] == []


def test_pagination_with_category_filter(client: TestClient) -> None:
    # camping: items 5, 6, 7, 8
    body = _page(client, category="camping", limit=2, offset=1)
    assert _ids(body) == [6, 7]
    assert body["total"] == 4


def test_first_page_unchanged(client: TestClient) -> None:
    assert _ids(_page(client, limit=5)) == [1, 2, 3, 4, 5]
    assert _ids(_page(client)) == list(range(1, 13))
