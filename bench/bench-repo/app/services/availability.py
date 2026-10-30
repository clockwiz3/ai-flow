"""Item availability over date ranges.

All ranges are half-open ``[start, end)``: an item reserved until ``end`` is back on the
morning of ``end`` and can be handed out again that same day.
"""

from datetime import date

from app.errors import ConflictError, InvalidRequestError
from app.models import Availability, Item, ItemStatus, Reservation, ReservationStatus
from app.services.catalog import get_item
from app.storage import Store


def validate_range(start: date, end: date) -> None:
    """Reject empty or inverted date ranges."""
    if end <= start:
        raise InvalidRequestError("end must be after start")


def _overlaps(existing: Reservation, start: date, end: date) -> bool:
    """Whether ``[start, end)`` collides with the existing reservation's range."""
    starts_inside = existing.start <= start < existing.end
    ends_inside = existing.start < end <= existing.end
    return starts_inside or ends_inside


def find_conflicts(
    store: Store,
    item_id: int,
    start: date,
    end: date,
    *,
    exclude_id: int | None = None,
) -> list[Reservation]:
    """Reservations of ``item_id`` that block the range ``[start, end)``."""
    conflicts: list[Reservation] = []
    for reservation in store.reservations.for_item(item_id):
        if reservation.id == exclude_id:
            continue
        if reservation.status is ReservationStatus.RETURNED:
            continue
        if _overlaps(reservation, start, end):
            conflicts.append(reservation)
    return conflicts


def _unavailable_reason(item: Item) -> str | None:
    if item.status is ItemStatus.MAINTENANCE:
        return "Item is under maintenance"
    if item.status is ItemStatus.RETIRED:
        return "Item is retired"
    return None


def check_availability(store: Store, item_id: int, start: date, end: date) -> Availability:
    """Describe whether ``item_id`` can be reserved for ``[start, end)`` and why not."""
    validate_range(start, end)
    item = get_item(store, item_id)

    reason = _unavailable_reason(item)
    conflicts = find_conflicts(store, item_id, start, end)
    if reason is None and conflicts:
        reason = "Item is already reserved for part of this period"

    return Availability(
        item_id=item_id,
        start=start,
        end=end,
        available=reason is None,
        reason=reason,
        conflicting_reservation_ids=[r.id for r in conflicts],
    )


def ensure_available(store: Store, item: Item, start: date, end: date) -> None:
    """Raise ``ConflictError`` unless ``item`` can be reserved for ``[start, end)``."""
    reason = _unavailable_reason(item)
    if reason is not None:
        raise ConflictError(f"Item {item.id} cannot be reserved: {reason.lower()}")
    conflicts = find_conflicts(store, item.id, start, end)
    if conflicts:
        ids = ", ".join(str(r.id) for r in conflicts)
        raise ConflictError(f"Item {item.id} is already reserved (reservations: {ids})")
