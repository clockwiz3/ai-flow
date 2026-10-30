"""Services are classes with constructor injection, wired through overridable FastAPI providers."""

import ast
import importlib
import inspect
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app
from app.clock import FixedClock
from app.errors import ConflictError, InvalidRequestError, NotFoundError
from app.models import Coupon, Item, ItemStatus, ReservationCreate, ReturnRequest
from app.seed import SEED_TODAY
from app.storage import Store

APP_DIR = Path(app.__file__).resolve().parent

CLASSES = {
    ("catalog", "CatalogService"): ["store"],
    ("customers", "CustomerService"): ["store"],
    ("pricing", "PricingService"): ["store"],
    ("availability", "AvailabilityService"): ["store", "catalog"],
    ("reservations", "ReservationService"): [
        "store", "clock", "catalog", "customers", "pricing", "availability",
    ],
    ("returns", "ReturnService"): ["store", "clock", "catalog", "reservations"],
    ("invoices", "InvoiceService"): ["store", "catalog", "customers", "pricing", "reservations"],
    ("reports", "ReportService"): ["store", "invoices"],
}

METHODS = {
    "CatalogService": ["list_categories", "get_category", "get_item", "list_items",
                       "create_item", "set_item_status"],
    "CustomerService": ["list_customers", "get_customer", "create_customer"],
    "PricingService": ["list_coupons", "lookup_coupon", "get_coupon", "create_coupon"],
    "AvailabilityService": ["find_conflicts", "check_availability", "ensure_available"],
    "ReservationService": ["get_reservation", "list_reservations", "create_reservation",
                           "cancel_reservation"],
    "ReturnService": ["return_reservation"],
    "InvoiceService": ["compute_invoice", "get_invoice"],
    "ReportService": ["revenue_report", "utilization_report"],
}

PURE_HELPERS = {
    "pricing": ["money", "rental_days", "free_days", "billable_days", "resolve_discounts",
                "quote_rental"],
    "availability": ["validate_range"],
    "returns": ["late_days", "late_rate", "late_fee"],
}

PROVIDERS = [
    "get_store", "get_clock", "get_catalog_service", "get_customer_service",
    "get_pricing_service", "get_availability_service", "get_reservation_service",
    "get_return_service", "get_invoice_service", "get_report_service",
]


def _cls(module: str, name: str) -> type:
    return getattr(importlib.import_module(f"app.services.{module}"), name)


def _services(store: Store, clock: FixedClock, **overrides: object) -> dict[str, object]:
    catalog = overrides.get("catalog") or _cls("catalog", "CatalogService")(store=store)
    customers = overrides.get("customers") or _cls("customers", "CustomerService")(store=store)
    pricing = overrides.get("pricing") or _cls("pricing", "PricingService")(store=store)
    availability = _cls("availability", "AvailabilityService")(store=store, catalog=catalog)
    reservations = _cls("reservations", "ReservationService")(
        store=store, clock=clock, catalog=catalog, customers=customers, pricing=pricing,
        availability=availability,
    )
    returns = _cls("returns", "ReturnService")(
        store=store, clock=clock, catalog=catalog, reservations=reservations
    )
    invoices = _cls("invoices", "InvoiceService")(
        store=store, catalog=catalog, customers=customers, pricing=pricing,
        reservations=reservations,
    )
    reports = _cls("reports", "ReportService")(store=store, invoices=invoices)
    return {
        "catalog": catalog, "customers": customers, "pricing": pricing,
        "availability": availability, "reservations": reservations, "returns": returns,
        "invoices": invoices, "reports": reports,
    }


# --- structure -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "params"), list(CLASSES.items()), ids=[name for _, name in CLASSES]
)
def test_service_class_constructor(key: tuple[str, str], params: list[str]) -> None:
    module, name = key
    cls = _cls(module, name)
    assert inspect.isclass(cls)
    signature = inspect.signature(cls.__init__)
    assert list(signature.parameters)[1:] == params
    for method in METHODS[name]:
        assert callable(getattr(cls, method, None)), f"{name}.{method} missing"


def test_old_service_functions_are_gone() -> None:
    for module_name in {m for m, _ in CLASSES}:
        module = importlib.import_module(f"app.services.{module_name}")
        for method in (m for (mod, cls), _ in CLASSES.items() if mod == module_name
                       for m in METHODS[cls]):
            assert not inspect.isfunction(getattr(module, method, None)), (
                f"app.services.{module_name}.{method} is still a module-level function"
            )


def test_no_module_level_function_takes_store_or_clock() -> None:
    for path in sorted((APP_DIR / "services").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                args = node.args
                names = {a.arg for a in [*args.posonlyargs, *args.args, *args.kwonlyargs]}
                assert not names & {"store", "clock"}, f"{path.name}:{node.name} takes {names}"


def test_pure_helpers_stay_module_level() -> None:
    for module_name, helpers in PURE_HELPERS.items():
        module = importlib.import_module(f"app.services.{module_name}")
        for helper in helpers:
            assert inspect.isfunction(getattr(module, helper, None)), f"{module_name}.{helper}"
    from app.services.pricing import money, quote_rental

    assert money(Decimal("2.345")) == Decimal("2.35")
    assert "store" not in inspect.signature(quote_rental).parameters


def test_api_layer_imports_only_classes_and_constants_from_services() -> None:
    for path in sorted((APP_DIR / "api").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith("app.services"), f"{path.name}: {alias.name}"
            elif isinstance(node, ast.ImportFrom) and node.module and (
                node.module == "app.services" or node.module.startswith("app.services.")
            ):
                for alias in node.names:
                    assert alias.name[:1].isupper(), (
                        f"{path.name} imports {alias.name!r} from {node.module}"
                    )


def test_route_handlers_do_not_take_the_store(app: FastAPI) -> None:
    from fastapi.routing import APIRoute

    routes = [r for r in app.routes if isinstance(r, APIRoute)]
    assert len(routes) >= 20
    for route in routes:
        params = inspect.signature(route.endpoint).parameters
        assert "store" not in params, f"{route.path} handler takes the store"


def test_providers_exist() -> None:
    dependencies = importlib.import_module("app.api.dependencies")
    for name in PROVIDERS:
        assert callable(getattr(dependencies, name, None)), name


# --- services used directly ------------------------------------------------------------


def test_services_work_when_constructed_directly() -> None:
    store = Store.seeded()
    clock = FixedClock(date(2025, 6, 10))
    s = _services(store, clock)

    assert [i.id for i in s["catalog"].list_items(q="Tent").items] == [5, 6]
    with pytest.raises(NotFoundError):
        s["catalog"].get_item(999)
    assert [c.id for c in s["customers"].list_customers()] == [1, 2, 3, 4, 5]
    assert s["pricing"].get_coupon("spring10").percent == 10

    with pytest.raises(InvalidRequestError):
        s["reservations"].create_reservation(
            ReservationCreate(item_id=1, customer_id=1, start=date(2025, 6, 5),
                              end=date(2025, 6, 8))
        )
    created = s["reservations"].create_reservation(
        ReservationCreate(item_id=1, customer_id=1, start=date(2025, 6, 12),
                          end=date(2025, 6, 15))
    )
    assert (created.id, created.created_on) == (7, date(2025, 6, 10))

    clock.set(date(2025, 6, 12))
    receipt = s["returns"].return_reservation(5, ReturnRequest())
    assert (receipt.returned_on, receipt.late_days) == (date(2025, 6, 12), 0)

    invoice = s["invoices"].get_invoice(4)
    assert invoice.total == Decimal("64.80")
    with pytest.raises(ConflictError):
        s["invoices"].get_invoice(3)
    revenue = s["reports"].revenue_report(date(2025, 5, 1), date(2025, 5, 15))
    assert revenue.total == Decimal("138.00")
    util = s["reports"].utilization_report(date(2025, 6, 1), date(2025, 6, 11))
    assert {r.item_id: r.reserved_days for r in util.rows}[2] == 3


def test_services_use_their_injected_collaborators() -> None:
    PricingService = _cls("pricing", "PricingService")
    CatalogService = _cls("catalog", "CatalogService")

    class MagicPricing(PricingService):  # type: ignore[misc, valid-type]
        def lookup_coupon(self, code: str) -> Coupon | None:
            return Coupon(code="MAGIC", percent=5)

    class BrokenCatalog(CatalogService):  # type: ignore[misc, valid-type]
        def get_item(self, item_id: int) -> Item:
            item = super().get_item(item_id)
            return item.model_copy(update={"status": ItemStatus.MAINTENANCE})

    store = Store.seeded()
    clock = FixedClock(SEED_TODAY)
    s = _services(store, clock, pricing=MagicPricing(store))
    booked = s["reservations"].create_reservation(
        ReservationCreate(item_id=1, customer_id=1, start=date(2025, 6, 5),
                          end=date(2025, 6, 8), coupon_code="ANYTHING")
    )
    assert booked.coupon_code == "MAGIC"

    s = _services(store, clock, catalog=BrokenCatalog(store))
    assert s["availability"].check_availability(1, date(2025, 6, 20),
                                                date(2025, 6, 22)).reason == (
        "Item is under maintenance"
    )
    with pytest.raises(ConflictError):
        s["reservations"].create_reservation(
            ReservationCreate(item_id=1, customer_id=1, start=date(2025, 6, 20),
                              end=date(2025, 6, 22))
        )


# --- dependency overrides --------------------------------------------------------------


def test_overriding_the_clock_reaches_every_service(app: FastAPI, client: TestClient,
                                                    clock: FixedClock) -> None:
    from app.api.dependencies import get_clock

    later = FixedClock(date(2025, 6, 10))
    app.dependency_overrides[get_clock] = lambda: later
    try:
        assert client.get("/health").json() == {"status": "ok", "today": "2025-06-10"}
        past = client.post(
            "/reservations",
            json={"item_id": 1, "customer_id": 1, "start": "2025-06-05", "end": "2025-06-08"},
        )
        assert past.status_code == 422
        created = client.post(
            "/reservations",
            json={"item_id": 1, "customer_id": 1, "start": "2025-06-10", "end": "2025-06-12"},
        )
        assert created.status_code == 201, created.text
        assert created.json()["created_on"] == "2025-06-10"
        receipt = client.post("/reservations/5/return")
        assert receipt.status_code == 200, receipt.text
        assert receipt.json()["returned_on"] == "2025-06-10"
    finally:
        app.dependency_overrides.clear()
    assert clock.today() == SEED_TODAY
    assert client.get("/health").json()["today"] == "2025-06-02"


def test_overriding_a_service_reaches_dependent_routes(app: FastAPI, client: TestClient,
                                                       store: Store) -> None:
    from app.api.dependencies import get_catalog_service

    CatalogService = _cls("catalog", "CatalogService")

    class RenamingCatalog(CatalogService):  # type: ignore[misc, valid-type]
        def get_item(self, item_id: int) -> Item:
            item = super().get_item(item_id)
            return item.model_copy(
                update={"name": f"Overridden {item.name}", "status": ItemStatus.MAINTENANCE}
            )

    app.dependency_overrides[get_catalog_service] = lambda: RenamingCatalog(store)
    try:
        body = client.get("/items/1").json()
        assert body["name"] == "Overridden Cordless Drill"
        availability = client.get(
            "/availability", params={"item_id": 1, "start": "2025-06-20", "end": "2025-06-22"}
        ).json()
        assert availability["reason"] == "Item is under maintenance"
        blocked = client.post(
            "/reservations",
            json={"item_id": 1, "customer_id": 1, "start": "2025-06-20", "end": "2025-06-22"},
        )
        assert blocked.status_code == 409
    finally:
        app.dependency_overrides.clear()
    assert client.get("/items/1").json()["name"] == "Cordless Drill"
    assert client.post(
        "/reservations",
        json={"item_id": 1, "customer_id": 1, "start": "2025-06-20", "end": "2025-06-22"},
    ).status_code == 201


def test_overriding_the_store(app: FastAPI, client: TestClient) -> None:
    from app.api.dependencies import get_store

    other = Store.seeded()
    other.coupons.insert(Coupon(code="OTHER50", percent=50))
    app.dependency_overrides[get_store] = lambda: other
    try:
        codes = [c["code"] for c in client.get("/coupons").json()]
        assert codes == ["OTHER50", "SPRING10", "WELCOME20"]
        created = client.post("/customers", json={"name": "Elsewhere", "email": "e@example.com"})
        assert created.status_code == 201
    finally:
        app.dependency_overrides.clear()
    assert len(other.customers) == 6
    assert len(client.get("/customers").json()) == 5
