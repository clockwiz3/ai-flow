"""The repositories are backed by SQLite and keep their exact interface and semantics."""

import ast
import sqlite3
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

import app.storage as storage_module
from app.clock import FixedClock
from app.main import create_app
from app.models import (
    Category,
    Coupon,
    CouponCreate,
    Customer,
    CustomerCreate,
    CustomerTier,
    Item,
    ItemCreate,
    ItemStatus,
    Reservation,
    ReservationStatus,
)
from app.seed import SEED_TODAY
from app.storage import Store, load_seed

REPOS = ("categories", "items", "customers", "reservations", "coupons")


def _sample_entities() -> dict[str, BaseModel]:
    return {
        "categories": Category(id="water", name="Water Sports"),
        "items": Item(
            id=40,
            name="Kayak",
            category="water",
            daily_rate=Decimal("12.50"),
            deposit=Decimal("200"),
            status=ItemStatus.MAINTENANCE,
        ),
        "customers": Customer(
            id=30, name="Zoe Park", email="zoe@example.com", tier=CustomerTier.SILVER
        ),
        "reservations": Reservation(
            id=50,
            item_id=40,
            customer_id=30,
            start=date(2025, 7, 1),
            end=date(2025, 7, 9),
            status=ReservationStatus.RETURNED,
            coupon_code="SPRING10",
            created_on=date(2025, 6, 20),
            returned_on=date(2025, 7, 10),
            damaged=True,
        ),
        "coupons": Coupon(code="AUTUMN15", percent=15),
    }


def _contains_model(value: object, depth: int = 0) -> bool:
    if isinstance(value, BaseModel):
        return True
    if depth > 3 or isinstance(value, (str, bytes)):
        return False
    if isinstance(value, dict):
        return any(
            _contains_model(k, depth + 1) or _contains_model(v, depth + 1)
            for k, v in value.items()
        )
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(_contains_model(v, depth + 1) for v in value)
    return False


# --- structure -------------------------------------------------------------------------


def test_storage_module_uses_sqlite3() -> None:
    tree = ast.parse(Path(storage_module.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    assert "sqlite3" in imported


def test_store_exposes_a_sqlite_connection() -> None:
    store = Store()
    assert isinstance(store.connection, sqlite3.Connection)
    assert isinstance(Store(":memory:").connection, sqlite3.Connection)
    assert isinstance(Store(db_path=":memory:").connection, sqlite3.Connection)


def test_no_entities_kept_in_python_containers() -> None:
    store = Store.seeded()
    for name, entity in _sample_entities().items():
        getattr(store, name).insert(entity)
    for name in REPOS:
        repo = getattr(store, name)
        assert len(repo) > 0
        for attr, value in vars(repo).items():
            assert not _contains_model(value), f"store.{name}.{attr} holds model instances"
    for attr, value in vars(store).items():
        if attr in REPOS:
            continue
        assert not _contains_model(value), f"store.{attr} holds model instances"


@pytest.mark.parametrize("name", REPOS)
def test_every_repository_writes_to_the_database(name: str) -> None:
    store = Store()
    before = store.connection.total_changes
    getattr(store, name).insert(_sample_entities()[name])
    assert store.connection.total_changes > before, f"{name} did not write to SQLite"


# --- round trips -----------------------------------------------------------------------


def test_round_trip_of_every_entity_type() -> None:
    store = Store()
    for name, entity in _sample_entities().items():
        repo = getattr(store, name)
        repo.insert(entity)
        key = entity.code if name == "coupons" else entity.id  # type: ignore[attr-defined]
        loaded = repo.get(key)
        assert loaded == entity, name
        assert type(loaded) is type(entity), name


def test_decimal_round_trip_is_exact() -> None:
    store = Store()
    store.categories.insert(Category(id="water", name="Water Sports"))
    values = ["12.50", "200", "0.10", "9999999999.99", "7", "0.05"]
    ids = []
    for i, raw in enumerate(values):
        created = store.items.create(
            ItemCreate(
                name=f"Thing {i}",
                category="water",
                daily_rate=Decimal("1.00") + i,
                deposit=Decimal(raw),
            )
        )
        ids.append(created.id)
    for item_id, raw in zip(ids, values, strict=True):
        loaded = store.items.get(item_id)
        assert loaded is not None
        assert isinstance(loaded.deposit, Decimal)
        assert str(loaded.deposit) == raw
        assert isinstance(loaded.daily_rate, Decimal)
    assert str(store.items.get(ids[0]).daily_rate) == "1.00"  # type: ignore[union-attr]


def test_dates_enums_and_bools_come_back_typed() -> None:
    store = Store.seeded()
    returned = store.reservations.get(1)
    assert returned is not None
    assert type(returned.start) is date and returned.start == date(2025, 5, 5)
    assert type(returned.end) is date and returned.end == date(2025, 5, 8)
    assert type(returned.created_on) is date and returned.created_on == date(2025, 5, 1)
    assert type(returned.returned_on) is date and returned.returned_on == date(2025, 5, 7)
    assert returned.status is ReservationStatus.RETURNED
    assert returned.damaged is False
    active = store.reservations.get(4)
    assert active is not None
    assert active.returned_on is None
    assert active.coupon_code is None
    assert active.status is ReservationStatus.ACTIVE

    damaged = active.model_copy(
        update={"status": ReservationStatus.RETURNED, "returned_on": date(2025, 6, 3),
                "damaged": True}
    )
    store.reservations.save(damaged)
    again = store.reservations.get(4)
    assert again == damaged
    assert again.damaged is True  # type: ignore[union-attr]
    assert again.status is ReservationStatus.RETURNED  # type: ignore[union-attr]

    assert store.items.get(4).status is ItemStatus.MAINTENANCE  # type: ignore[union-attr]
    assert store.items.get(12).status is ItemStatus.RETIRED  # type: ignore[union-attr]
    assert store.customers.get(3).tier is CustomerTier.GOLD  # type: ignore[union-attr]
    assert store.items.get(6).daily_rate == Decimal("35.00")  # type: ignore[union-attr]
    assert str(store.items.get(8).daily_rate) == "6.50"  # type: ignore[union-attr]


# --- repository semantics --------------------------------------------------------------


def test_seeded_store_matches_seed_data() -> None:
    from app import seed

    store = Store.seeded()
    assert store.categories.all() == sorted(seed.CATEGORIES, key=lambda c: c.id)
    assert store.items.all() == seed.ITEMS
    assert store.customers.all() == seed.CUSTOMERS
    assert store.coupons.all() == seed.COUPONS
    assert store.reservations.all() == seed.RESERVATIONS
    assert list(store.items) == seed.ITEMS
    assert len(store.items) == 12
    assert len(store.reservations) == 6
    assert "camping" in store.categories
    assert "water" not in store.categories
    assert 12 in store.items and 13 not in store.items
    assert "SPRING10" in store.coupons and "NOPE" not in store.coupons


def test_insert_duplicate_raises_key_error_and_save_replaces() -> None:
    store = Store.seeded()
    with pytest.raises(KeyError):
        store.items.insert(store.items.get(1))  # type: ignore[arg-type]
    with pytest.raises(KeyError):
        store.categories.insert(Category(id="tools", name="Other"))
    with pytest.raises(KeyError):
        store.coupons.insert(Coupon(code="SPRING10", percent=50))
    assert store.coupons.get("SPRING10").percent == 10  # type: ignore[union-attr]

    renamed = store.items.get(1).model_copy(update={"name": "Drill v2"})  # type: ignore[union-attr]
    assert store.items.save(renamed) == renamed
    assert store.items.get(1) == renamed
    assert len(store.items) == 12
    new_category = Category(id="water", name="Water")
    store.categories.save(new_category)
    assert store.categories.get("water") == new_category


def test_lookups_and_filters() -> None:
    store = Store.seeded()
    assert store.coupons.get("  spring10 ") == Coupon(code="SPRING10", percent=10)
    assert store.coupons.get("nope") is None
    assert store.customers.by_email(" CARLA@Example.com ").id == 3  # type: ignore[union-attr]
    assert store.customers.by_email("nobody@example.com") is None
    assert store.items.get(999) is None
    assert store.categories.get("nope") is None
    assert [r.id for r in store.reservations.for_customer(2)] == [3, 6]
    assert [r.id for r in store.reservations.for_item(5)] == [2]
    assert store.reservations.for_item(11) == []


def test_id_assignment_is_unchanged() -> None:
    store = Store()
    store.categories.insert(Category(id="water", name="Water"))
    data = ItemCreate(name="Kayak", category="water", daily_rate=Decimal("10.00"),
                      deposit=Decimal("0"))
    assert store.items.create(data).id == 1
    assert store.items.create(data).id == 2
    store.items.insert(Item(id=10, **data.model_dump()))
    assert store.items.create(data).id == 11
    store.items.insert(Item(id=5, **data.model_dump()))
    assert store.items.create(data).id == 12
    assert store.items.allocate_id() == 13
    assert store.items.allocate_id() == 14
    assert store.items.create(data).id == 15

    assert store.customers.allocate_id() == 1
    created = store.customers.create(CustomerCreate(name="Ann", email="ann@example.com"))
    assert created.id == 2

    seeded = Store.seeded()
    assert seeded.reservations.allocate_id() == 7
    assert seeded.customers.create(CustomerCreate(name="Bo", email="bo@example.com")).id == 6
    assert seeded.coupons.create(CouponCreate(code="new5", percent=5)) == Coupon(
        code="NEW5", percent=5
    )


# --- isolation and persistence ---------------------------------------------------------


def test_in_memory_stores_are_isolated() -> None:
    first = Store.seeded()
    second = Store.seeded()
    first.customers.create(CustomerCreate(name="Only Here", email="here@example.com"))
    first.coupons.create(CouponCreate(code="ONLYHERE", percent=5))
    assert len(first.customers) == 6
    assert len(second.customers) == 5
    assert second.coupons.get("ONLYHERE") is None
    assert second.customers.create(CustomerCreate(name="X", email="x@example.com")).id == 6

    empty = Store()
    for name in REPOS:
        assert len(getattr(empty, name)) == 0
        assert getattr(empty, name).all() == []


def test_apps_with_default_stores_are_isolated() -> None:
    clock = FixedClock(SEED_TODAY)
    with TestClient(create_app(clock=clock)) as one, TestClient(create_app(clock=clock)) as two:
        created = one.post("/customers", json={"name": "Solo", "email": "solo@example.com"})
        assert created.status_code == 201
        assert created.json()["id"] == 6
        assert len(one.get("/customers").json()) == 6
        assert len(two.get("/customers").json()) == 5
        again = two.post("/customers", json={"name": "Solo", "email": "solo@example.com"})
        assert again.status_code == 201
        assert again.json()["id"] == 6


def test_file_database_is_shared_between_stores(tmp_path: Path) -> None:
    db_file = str(tmp_path / "rentwise.db")
    first = Store(db_path=db_file)
    load_seed(first)
    entities = _sample_entities()
    for name, entity in entities.items():
        getattr(first, name).insert(entity)
    cancelled = first.reservations.get(5).model_copy(  # type: ignore[union-attr]
        update={"status": ReservationStatus.CANCELLED}
    )
    first.reservations.save(cancelled)

    second = Store(db_path=db_file)
    assert second.categories.get("water") == entities["categories"]
    assert second.items.get(40) == entities["items"]
    assert second.customers.get(30) == entities["customers"]
    assert second.reservations.get(50) == entities["reservations"]
    assert second.coupons.get("autumn15") == entities["coupons"]
    assert second.reservations.get(5).status is ReservationStatus.CANCELLED  # type: ignore[union-attr]
    assert len(second.items) == 13
    assert second.items.allocate_id() == 41
    assert second.customers.allocate_id() == 31
    assert second.reservations.allocate_id() == 51


def test_api_writes_land_in_the_database(tmp_path: Path) -> None:
    db_file = str(tmp_path / "api.db")
    store = Store(db_path=db_file)
    load_seed(store)
    with TestClient(create_app(store=store, clock=FixedClock(SEED_TODAY))) as client:
        created = client.post(
            "/reservations",
            json={"item_id": 7, "customer_id": 2, "start": "2025-06-03", "end": "2025-06-06",
                  "coupon_code": "welcome20"},
        )
        assert created.status_code == 201, created.text
        assert client.post("/reservations/4/return", json={"damaged": True}).status_code == 200

    reopened = Store(db_path=db_file)
    booking = reopened.reservations.get(7)
    assert booking is not None
    assert booking.coupon_code == "WELCOME20"
    assert booking.created_on == date(2025, 6, 2)
    returned = reopened.reservations.get(4)
    assert returned.status is ReservationStatus.RETURNED  # type: ignore[union-attr]
    assert returned.returned_on == date(2025, 6, 2)  # type: ignore[union-attr]
    assert returned.damaged is True  # type: ignore[union-attr]
    assert reopened.items.get(2).status is ItemStatus.MAINTENANCE  # type: ignore[union-attr]
