from fastapi import FastAPI
from fastapi.testclient import TestClient


def _search(client: TestClient, **params) -> dict:
    response = client.get("/items", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def _ids(body: dict) -> list[int]:
    return [item["id"] for item in body["items"]]


def test_lower_case_query_finds_items(client: TestClient) -> None:
    body = _search(client, q="tent")
    assert _ids(body) == [5, 6]
    assert body["total"] == 2


def test_upper_and_mixed_case_queries(client: TestClient) -> None:
    assert _ids(_search(client, q="TENT")) == [5, 6]
    assert _ids(_search(client, q="fAmIlY")) == [6]
    assert _ids(_search(client, q="cordless drill")) == [1]


def test_original_case_still_matches(client: TestClient) -> None:
    assert _ids(_search(client, q="Tent")) == [5, 6]
    assert _ids(_search(client, q="Camera")) == [9]


def test_case_insensitive_with_category(client: TestClient) -> None:
    assert _ids(_search(client, q="TENT", category="camping")) == [5, 6]
    assert _search(client, q="tent", category="tools")["items"] == []


def test_no_match(client: TestClient) -> None:
    body = _search(client, q="kayak")
    assert body["items"] == []
    assert body["total"] == 0


def test_no_debug_customers_endpoint(client: TestClient) -> None:
    assert client.get("/debug/customers").status_code == 404


def test_no_debug_routes_registered(app: FastAPI) -> None:
    paths = [getattr(route, "path", "") for route in app.routes]
    assert not [path for path in paths if "debug" in path.lower()]


def test_no_extra_customer_routes(app: FastAPI) -> None:
    paths = {getattr(route, "path", "") for route in app.routes}
    assert {path for path in paths if "customer" in path.lower()} <= {
        "/customers",
        "/customers/{customer_id}",
    }
