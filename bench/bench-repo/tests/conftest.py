from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.clock import FixedClock
from app.main import create_app
from app.seed import SEED_TODAY
from app.storage import Store


@pytest.fixture
def clock() -> FixedClock:
    """Clock pinned to the seed's reference date (2025-06-02)."""
    return FixedClock(SEED_TODAY)


@pytest.fixture
def store() -> Store:
    return Store.seeded()


@pytest.fixture
def app(store: Store, clock: FixedClock) -> FastAPI:
    return create_app(store=store, clock=clock)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def reserve(client: TestClient):
    """Create a reservation through the API and return its JSON body."""

    def _reserve(
        item_id: int,
        customer_id: int,
        start: str,
        end: str,
        coupon_code: str | None = None,
    ) -> dict:
        payload = {"item_id": item_id, "customer_id": customer_id, "start": start, "end": end}
        if coupon_code is not None:
            payload["coupon_code"] = coupon_code
        response = client.post("/reservations", json=payload)
        assert response.status_code == 201, response.text
        return response.json()

    return _reserve
