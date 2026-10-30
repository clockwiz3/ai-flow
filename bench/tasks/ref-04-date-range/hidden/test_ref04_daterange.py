"""DateRange value object and its use by availability, reservations and reports."""

import dataclasses
import re
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app
from app.daterange import DateRange
from app.models import Reservation

SERVICES = Path(app.__file__).resolve().parent / "services"


def d(day: int, month: int = 6) -> date:
    return date(2025, month, day)


def r(start: int, end: int) -> DateRange:
    return DateRange(d(start), d(end))


# --- the value object -------------------------------------------------------------------


def test_fields_and_immutability() -> None:
    rng = DateRange(start=d(10), end=d(15))
    assert (rng.start, rng.end) == (d(10), d(15))
    assert dataclasses.is_dataclass(rng)
    with pytest.raises(dataclasses.FrozenInstanceError):
        rng.start = d(1)  # type: ignore[misc]
    assert rng == r(10, 15)
    assert hash(rng) == hash(r(10, 15))
    assert rng != r(10, 16)


@pytest.mark.parametrize(("start", "end"), [(d(10), d(10)), (d(11), d(10)), (d(1, 7), d(30))])
def test_empty_or_inverted_ranges_are_rejected(start: date, end: date) -> None:
    with pytest.raises(ValueError):
        DateRange(start, end)


def test_days() -> None:
    assert r(10, 15).days == 5
    assert r(10, 11).days == 1
    assert DateRange(d(25, 5), d(3, 6)).days == 9
    assert DateRange(date(2024, 2, 28), date(2024, 3, 1)).days == 2


def test_contains_is_half_open() -> None:
    rng = r(10, 15)
    assert rng.contains(d(10))
    assert rng.contains(d(12))
    assert rng.contains(d(14))
    assert not rng.contains(d(15))
    assert not rng.contains(d(9))
    assert not rng.contains(d(20))


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ((10, 15), (12, 14), True),  # b inside a
        ((12, 14), (10, 15), True),  # a inside b (containment)
        ((10, 15), (9, 16), True),  # b wraps around a
        ((10, 15), (10, 15), True),  # identical
        ((10, 15), (8, 11), True),  # b ends inside a
        ((10, 15), (14, 20), True),  # b starts inside a
        ((10, 15), (10, 11), True),  # same start
        ((10, 15), (14, 15), True),  # same end
        ((10, 15), (15, 20), False),  # touching: b starts the day a ends
        ((10, 15), (5, 10), False),  # touching: b ends the day a starts
        ((10, 15), (16, 20), False),
        ((10, 15), (1, 9), False),
        ((10, 11), (11, 12), False),
    ],
)
def test_overlaps(a: tuple[int, int], b: tuple[int, int], expected: bool) -> None:
    first, second = r(*a), r(*b)
    assert first.overlaps(second) is expected
    assert second.overlaps(first) is expected


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ((10, 15), (12, 14), 2),
        ((10, 15), (1, 30), 5),
        ((10, 15), (13, 20), 2),
        ((10, 15), (15, 20), 0),
        ((10, 15), (20, 25), 0),
        ((10, 15), (10, 15), 5),
    ],
)
def test_overlap_days(a: tuple[int, int], b: tuple[int, int], expected: int) -> None:
    assert r(*a).overlap_days(r(*b)) == expected
    assert r(*b).overlap_days(r(*a)) == expected


def test_reservation_period() -> None:
    reservation = Reservation(
        id=1, item_id=1, customer_id=1, start=d(10), end=d(15), created_on=d(1)
    )
    assert reservation.period == r(10, 15)
    assert isinstance(reservation.period, DateRange)
    assert reservation.days == 5


# --- it is actually used ----------------------------------------------------------------


@pytest.mark.parametrize("module", ["availability.py", "reports.py"])
def test_services_use_date_range(module: str) -> None:
    source = (SERVICES / module).read_text(encoding="utf-8")
    assert "DateRange" in source or ".period" in source, module


@pytest.mark.parametrize("module", ["availability.py", "reservations.py", "reports.py"])
def test_no_ad_hoc_date_arithmetic(module: str) -> None:
    source = (SERVICES / module).read_text(encoding="utf-8")
    assert not re.search(r"end\)?\s*-\s*(max\()?[\w.]*start", source), module


def test_validate_range_returns_a_date_range() -> None:
    from app.errors import InvalidRequestError
    from app.services.availability import validate_range

    assert validate_range(d(10), d(15)) == r(10, 15)
    with pytest.raises(InvalidRequestError):
        validate_range(d(10), d(10))


def test_availability_no_longer_has_ad_hoc_overlap_logic() -> None:
    source = (SERVICES / "availability.py").read_text(encoding="utf-8")
    assert ".overlaps(" in source
    assert "starts_inside" not in source
    assert "ends_inside" not in source


def test_range_wrapping_an_existing_reservation_conflicts(client: TestClient) -> None:
    # reservation 5: item 6, 2025-06-10 .. 2025-06-15 (active)
    body = client.get(
        "/availability", params={"item_id": 6, "start": "2025-06-09", "end": "2025-06-16"}
    ).json()
    assert body["available"] is False
    assert body["conflicting_reservation_ids"] == [5]
    response = client.post(
        "/reservations",
        json={"item_id": 6, "customer_id": 1, "start": "2025-06-09", "end": "2025-06-16"},
    )
    assert response.status_code == 409


def test_touching_ranges_still_allowed(client: TestClient, reserve) -> None:
    reserve(6, 1, "2025-06-15", "2025-06-20")
    reserve(6, 2, "2025-06-05", "2025-06-10")
    body = client.get(
        "/availability", params={"item_id": 6, "start": "2025-06-20", "end": "2025-06-22"}
    ).json()
    assert body["available"] is True


def test_invalid_ranges_keep_their_error(client: TestClient) -> None:
    for path, params in [
        ("/availability", {"item_id": 6, "start": "2025-06-09", "end": "2025-06-09"}),
        ("/reports/revenue", {"start": "2025-06-09", "end": "2025-06-01"}),
        ("/reports/utilization", {"start": "2025-06-09", "end": "2025-06-09"}),
    ]:
        response = client.get(path, params=params)
        assert response.status_code == 422, path
        assert response.json() == {"detail": "end must be after start", "code": "invalid_request"}
    response = client.post(
        "/reservations",
        json={"item_id": 6, "customer_id": 1, "start": "2025-06-09", "end": "2025-06-08"},
    )
    assert response.status_code == 422
    assert response.json() == {"detail": "end must be after start", "code": "invalid_request"}
    too_long = client.post(
        "/reservations",
        json={"item_id": 6, "customer_id": 1, "start": "2025-06-20", "end": "2025-09-19"},
    )
    assert too_long.status_code == 422
    assert too_long.json()["detail"] == "Reservations are limited to 90 days"
