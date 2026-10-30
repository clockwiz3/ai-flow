"""Demo data loaded into a fresh store.

Dates are chosen around ``SEED_TODAY`` (2025-06-02), the date the test clock is pinned to.
"""

from datetime import date
from decimal import Decimal

from app.models import (
    Category,
    Coupon,
    Customer,
    CustomerTier,
    Item,
    ItemStatus,
    Reservation,
    ReservationStatus,
)

SEED_TODAY = date(2025, 6, 2)

CATEGORIES: list[Category] = [
    Category(id="tools", name="Power Tools"),
    Category(id="camping", name="Camping"),
    Category(id="photo", name="Photo & Video"),
    Category(id="garden", name="Garden"),
]


def _item(
    item_id: int,
    name: str,
    category: str,
    daily_rate: str,
    deposit: str,
    status: ItemStatus = ItemStatus.AVAILABLE,
) -> Item:
    return Item(
        id=item_id,
        name=name,
        category=category,
        daily_rate=Decimal(daily_rate),
        deposit=Decimal(deposit),
        status=status,
    )


ITEMS: list[Item] = [
    _item(1, "Cordless Drill", "tools", "12.00", "50.00"),
    _item(2, "Circular Saw", "tools", "18.00", "80.00"),
    _item(3, "Rotary Hammer", "tools", "25.00", "120.00"),
    _item(4, "Tile Cutter", "tools", "15.00", "60.00", ItemStatus.MAINTENANCE),
    _item(5, "Two-Person Tent", "camping", "20.00", "100.00"),
    _item(6, "Family Tent", "camping", "35.00", "150.00"),
    _item(7, "Sleeping Bag", "camping", "8.00", "30.00"),
    _item(8, "Camping Stove", "camping", "6.50", "25.00"),
    _item(9, "Mirrorless Camera", "photo", "45.00", "400.00"),
    _item(10, "Telephoto Lens", "photo", "30.00", "300.00"),
    _item(11, "Hedge Trimmer", "garden", "14.00", "60.00"),
    _item(12, "Lawn Aerator", "garden", "16.00", "70.00", ItemStatus.RETIRED),
]

CUSTOMERS: list[Customer] = [
    Customer(id=1, name="Alice Martin", email="alice@example.com", tier=CustomerTier.REGULAR),
    Customer(id=2, name="Bob Chen", email="bob@example.com", tier=CustomerTier.SILVER),
    Customer(id=3, name="Carla Diaz", email="carla@example.com", tier=CustomerTier.GOLD),
    Customer(id=4, name="Dmitri Ivanov", email="dmitri@example.com", tier=CustomerTier.REGULAR),
    Customer(id=5, name="Emma Novak", email="emma@example.com", tier=CustomerTier.GOLD),
]

COUPONS: list[Coupon] = [
    Coupon(code="SPRING10", percent=10),
    Coupon(code="WELCOME20", percent=20),
]


def _reservation(
    reservation_id: int,
    item_id: int,
    customer_id: int,
    start: date,
    end: date,
    created_on: date,
    status: ReservationStatus = ReservationStatus.ACTIVE,
    returned_on: date | None = None,
) -> Reservation:
    return Reservation(
        id=reservation_id,
        item_id=item_id,
        customer_id=customer_id,
        start=start,
        end=end,
        status=status,
        created_on=created_on,
        returned_on=returned_on,
    )


_RETURNED = ReservationStatus.RETURNED
_CANCELLED = ReservationStatus.CANCELLED

RESERVATIONS: list[Reservation] = [
    # past, returned early
    _reservation(
        1,
        1,
        1,
        date(2025, 5, 5),
        date(2025, 5, 8),
        date(2025, 5, 1),
        _RETURNED,
        returned_on=date(2025, 5, 7),
    ),
    _reservation(
        2,
        5,
        3,
        date(2025, 5, 10),
        date(2025, 5, 17),
        date(2025, 5, 2),
        _RETURNED,
        returned_on=date(2025, 5, 16),
    ),
    # past, cancelled
    _reservation(3, 9, 2, date(2025, 5, 20), date(2025, 5, 23), date(2025, 5, 12), _CANCELLED),
    # running and upcoming
    _reservation(4, 2, 4, date(2025, 6, 1), date(2025, 6, 4), date(2025, 5, 28)),
    _reservation(5, 6, 5, date(2025, 6, 10), date(2025, 6, 15), date(2025, 5, 30)),
    _reservation(6, 10, 2, date(2025, 6, 5), date(2025, 6, 8), date(2025, 5, 31), _CANCELLED),
]
