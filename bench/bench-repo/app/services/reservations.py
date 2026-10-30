"""Reservation lifecycle: create, look up, cancel."""

from app.clock import Clock
from app.errors import ConflictError, InvalidRequestError, NotFoundError
from app.models import Reservation, ReservationCreate, ReservationStatus
from app.services.availability import ensure_available, validate_range
from app.services.catalog import get_item
from app.services.customers import get_customer
from app.services.pricing import lookup_coupon
from app.storage import Store

MAX_RENTAL_DAYS = 90


def get_reservation(store: Store, reservation_id: int) -> Reservation:
    reservation = store.reservations.get(reservation_id)
    if reservation is None:
        raise NotFoundError(f"Reservation {reservation_id} not found")
    return reservation


def list_reservations(
    store: Store,
    *,
    customer_id: int | None = None,
    item_id: int | None = None,
    status: ReservationStatus | None = None,
) -> list[Reservation]:
    """Reservations ordered by id, optionally filtered."""
    result = store.reservations.all()
    if customer_id is not None:
        result = [r for r in result if r.customer_id == customer_id]
    if item_id is not None:
        result = [r for r in result if r.item_id == item_id]
    if status is not None:
        result = [r for r in result if r.status is status]
    return result


def create_reservation(store: Store, clock: Clock, data: ReservationCreate) -> Reservation:
    """Book an item for a customer.

    Rules: the range must be non-empty, start today or later and be at most
    ``MAX_RENTAL_DAYS`` long; item and customer must exist; a coupon code, if given, must
    exist; the item must be available (not in maintenance / retired, no overlapping active
    reservation).
    """
    validate_range(data.start, data.end)
    today = clock.today()
    if data.start < today:
        raise InvalidRequestError("Reservations cannot start in the past")
    if (data.end - data.start).days > MAX_RENTAL_DAYS:
        raise InvalidRequestError(f"Reservations are limited to {MAX_RENTAL_DAYS} days")

    item = get_item(store, data.item_id)
    customer = get_customer(store, data.customer_id)

    coupon_code: str | None = None
    if data.coupon_code:
        coupon = lookup_coupon(store, data.coupon_code)
        if coupon is None:
            raise InvalidRequestError(f"Unknown coupon code {data.coupon_code!r}")
        coupon_code = coupon.code

    ensure_available(store, item, data.start, data.end)

    reservation = Reservation(
        id=store.reservations.allocate_id(),
        item_id=item.id,
        customer_id=customer.id,
        start=data.start,
        end=data.end,
        coupon_code=coupon_code,
        created_on=today,
    )
    return store.reservations.insert(reservation)


def cancel_reservation(store: Store, reservation_id: int) -> Reservation:
    """Cancel an active reservation. Returned or already cancelled ones cannot be cancelled."""
    reservation = get_reservation(store, reservation_id)
    if reservation.status is not ReservationStatus.ACTIVE:
        raise ConflictError(
            f"Reservation {reservation_id} is {reservation.status.value} and cannot be cancelled"
        )
    cancelled = reservation.model_copy(update={"status": ReservationStatus.CANCELLED})
    return store.reservations.save(cancelled)
