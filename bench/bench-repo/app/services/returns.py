"""Handling item returns: late fees and deposits."""

from datetime import date, timedelta
from decimal import Decimal

from app.clock import Clock
from app.errors import ConflictError, InvalidRequestError
from app.models import ItemStatus, ReservationStatus, ReturnReceipt, ReturnRequest
from app.services.catalog import get_item
from app.services.pricing import ZERO, money
from app.services.reservations import get_reservation
from app.storage import Store

LATE_FEE_MULTIPLIER = Decimal("1.5")


def late_days(end: date, returned_on: date) -> int:
    """Number of chargeable late days for an item due back on ``end``.

    ``end`` is exclusive, so the last day the customer paid for is ``end - 1``.
    """
    last_rental_day = end - timedelta(days=1)
    return max(0, (returned_on - last_rental_day).days)


def late_rate(daily_rate: Decimal) -> Decimal:
    """Price of one late day."""
    return daily_rate * LATE_FEE_MULTIPLIER


def late_fee(daily_rate: Decimal, days_late: int) -> Decimal:
    return money(late_rate(daily_rate) * days_late)


def return_reservation(
    store: Store, clock: Clock, reservation_id: int, request: ReturnRequest
) -> ReturnReceipt:
    """Register the return of a reserved item.

    The return date defaults to today and may be neither before the reservation start nor in
    the future. A damaged item keeps the deposit and goes to maintenance; otherwise the
    deposit is refunded in full.
    """
    reservation = get_reservation(store, reservation_id)
    if reservation.status is not ReservationStatus.ACTIVE:
        raise ConflictError(
            f"Reservation {reservation_id} is {reservation.status.value} and cannot be returned"
        )

    today = clock.today()
    returned_on = request.returned_on or today
    if returned_on < reservation.start:
        raise InvalidRequestError("Return date is before the reservation start")
    if returned_on > today:
        raise InvalidRequestError("Return date cannot be in the future")

    item = get_item(store, reservation.item_id)
    days_late = late_days(reservation.end, returned_on)
    fee = late_fee(item.daily_rate, days_late)

    store.reservations.save(
        reservation.model_copy(
            update={
                "status": ReservationStatus.RETURNED,
                "returned_on": returned_on,
                "damaged": request.damaged,
            }
        )
    )
    if request.damaged and item.status is ItemStatus.AVAILABLE:
        store.items.save(item.model_copy(update={"status": ItemStatus.MAINTENANCE}))

    withheld = item.deposit if request.damaged else ZERO
    return ReturnReceipt(
        reservation_id=reservation.id,
        returned_on=returned_on,
        late_days=days_late,
        late_fee=fee,
        damaged=request.damaged,
        deposit=item.deposit,
        deposit_refunded=money(item.deposit - withheld),
        deposit_withheld=money(withheld),
    )
