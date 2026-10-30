"""The HTTP layer is split into one router module per resource; the route table is unchanged."""

import importlib
import re
from pathlib import Path

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute

import app

API_DIR = Path(app.__file__).resolve().parent / "api"

# (method, path, handler name, tags, explicit status code) - the route table before the split
EXPECTED = {
    "health": [
        ("GET", "/health", "health", ["meta"], None),
    ],
    "catalog": [
        ("GET", "/categories", "list_categories", ["catalog"], None),
        ("GET", "/items", "list_items", ["catalog"], None),
        ("POST", "/items", "create_item", ["catalog"], 201),
        ("GET", "/items/{item_id}", "get_item", ["catalog"], None),
        ("POST", "/items/{item_id}/status", "set_item_status", ["catalog"], None),
    ],
    "customers": [
        ("GET", "/customers", "list_customers", ["customers"], None),
        ("POST", "/customers", "create_customer", ["customers"], 201),
        ("GET", "/customers/{customer_id}", "get_customer", ["customers"], None),
    ],
    "coupons": [
        ("GET", "/coupons", "list_coupons", ["pricing"], None),
        ("POST", "/coupons", "create_coupon", ["pricing"], 201),
    ],
    "availability": [
        ("GET", "/availability", "get_availability", ["reservations"], None),
    ],
    "reservations": [
        ("GET", "/reservations", "list_reservations", ["reservations"], None),
        ("POST", "/reservations", "create_reservation", ["reservations"], 201),
        ("GET", "/reservations/{reservation_id}", "get_reservation", ["reservations"], None),
        (
            "POST",
            "/reservations/{reservation_id}/cancel",
            "cancel_reservation",
            ["reservations"],
            None,
        ),
        (
            "POST",
            "/reservations/{reservation_id}/return",
            "return_reservation",
            ["reservations"],
            None,
        ),
        ("GET", "/reservations/{reservation_id}/invoice", "get_invoice", ["reservations"], None),
    ],
    "reports": [
        ("GET", "/reports/revenue", "revenue_report", ["reports"], None),
        ("GET", "/reports/utilization", "utilization_report", ["reports"], None),
    ],
}


def _describe(routes) -> set[tuple]:
    rows = set()
    for route in routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods:
            rows.add((method, route.path, route.endpoint.__name__, tuple(route.tags),
                      route.status_code))
    return rows


def _expected(rows) -> set[tuple]:
    return {(m, p, name, tuple(tags), code) for m, p, name, tags, code in rows}


def test_routes_module_is_gone() -> None:
    assert not (API_DIR / "routes.py").exists()
    with pytest.raises(ImportError):
        importlib.import_module("app.api.routes")


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_resource_module_has_its_router(name: str) -> None:
    module = importlib.import_module(f"app.api.{name}")
    router = module.router
    assert isinstance(router, APIRouter)
    assert _describe(router.routes) == _expected(EXPECTED[name])


def test_app_route_table_is_unchanged(app: FastAPI) -> None:
    every = set()
    for rows in EXPECTED.values():
        every |= _expected(rows)
    assert _describe(app.routes) == every


def test_app_serves_handlers_from_resource_modules(app: FastAPI) -> None:
    owner = {}
    for name, rows in EXPECTED.items():
        for method, path, *_ in rows:
            owner[(method, path)] = f"app.api.{name}"
    seen = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods:
            assert route.endpoint.__module__ == owner[(method, route.path)], (method, route.path)
            seen.add((method, route.path))
    assert seen == set(owner)


def test_openapi_operations_are_unchanged(app: FastAPI) -> None:
    schema = app.openapi()
    operations = {
        (method.upper(), path, op["operationId"], tuple(op.get("tags", [])))
        for path, methods in schema["paths"].items()
        for method, op in methods.items()
    }
    expected = set()
    for rows in EXPECTED.values():
        for method, path, name, tags, _ in rows:
            op_id = re.sub(r"\W", "_", name + path) + "_" + method.lower()
            expected.add((method, path, op_id, tuple(tags)))
    assert operations == expected
    for path, methods in schema["paths"].items():
        for method, op in methods.items():
            codes = set(op["responses"])
            if (method.upper(), path) in {("POST", "/items"), ("POST", "/customers"),
                                          ("POST", "/coupons"), ("POST", "/reservations")}:
                assert "201" in codes, (method, path)
            else:
                assert "200" in codes, (method, path)
