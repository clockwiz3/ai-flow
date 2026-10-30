"""In-memory repositories and the ``Store`` that groups them.

Nothing here knows about business rules; repositories only store, fetch and allocate ids.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field

from pydantic import BaseModel

from app.models import (
    Category,
    Coupon,
    CouponCreate,
    Customer,
    CustomerCreate,
    Item,
    ItemCreate,
    Reservation,
)


class InMemoryRepository[K, T: BaseModel]:
    """Dictionary-backed repository keyed by ``K``."""

    def __init__(self) -> None:
        self._rows: dict[K, T] = {}

    def _key(self, entity: T) -> K:
        raise NotImplementedError

    def insert(self, entity: T) -> T:
        """Add a new entity; its key must not exist yet."""
        key = self._key(entity)
        if key in self._rows:
            raise KeyError(f"duplicate key {key!r}")
        self._rows[key] = entity
        return entity

    def save(self, entity: T) -> T:
        """Insert or replace an entity."""
        self._rows[self._key(entity)] = entity
        return entity

    def get(self, key: K) -> T | None:
        return self._rows.get(key)

    def all(self) -> list[T]:
        """All entities ordered by key."""
        return [self._rows[key] for key in sorted(self._rows)]  # type: ignore[type-var]

    def __iter__(self) -> Iterator[T]:
        return iter(self.all())

    def __len__(self) -> int:
        return len(self._rows)

    def __contains__(self, key: object) -> bool:
        return key in self._rows


class IntIdRepository[T: BaseModel](InMemoryRepository[int, T]):
    """Repository for entities with an auto-incrementing integer ``id``."""

    def __init__(self) -> None:
        super().__init__()
        self._next_id = 1

    def _key(self, entity: T) -> int:
        return entity.id  # type: ignore[attr-defined]

    def allocate_id(self) -> int:
        new_id = self._next_id
        self._next_id += 1
        return new_id

    def insert(self, entity: T) -> T:
        stored = super().insert(entity)
        self._next_id = max(self._next_id, self._key(entity) + 1)
        return stored


class CategoryRepository(InMemoryRepository[str, Category]):
    def _key(self, entity: Category) -> str:
        return entity.id


class ItemRepository(IntIdRepository[Item]):
    def create(self, data: ItemCreate) -> Item:
        return self.insert(Item(id=self.allocate_id(), **data.model_dump()))


class CustomerRepository(IntIdRepository[Customer]):
    def create(self, data: CustomerCreate) -> Customer:
        return self.insert(Customer(id=self.allocate_id(), **data.model_dump()))

    def by_email(self, email: str) -> Customer | None:
        email = email.strip().lower()
        return next((c for c in self._rows.values() if c.email == email), None)


class ReservationRepository(IntIdRepository[Reservation]):
    def for_item(self, item_id: int) -> list[Reservation]:
        return [r for r in self.all() if r.item_id == item_id]

    def for_customer(self, customer_id: int) -> list[Reservation]:
        return [r for r in self.all() if r.customer_id == customer_id]


class CouponRepository(InMemoryRepository[str, Coupon]):
    def _key(self, entity: Coupon) -> str:
        return entity.code

    def create(self, data: CouponCreate) -> Coupon:
        return self.insert(Coupon(**data.model_dump()))

    def get(self, key: str) -> Coupon | None:
        return super().get(key.strip().upper())


@dataclass
class Store:
    """All repositories of one running application instance."""

    categories: CategoryRepository = field(default_factory=CategoryRepository)
    items: ItemRepository = field(default_factory=ItemRepository)
    customers: CustomerRepository = field(default_factory=CustomerRepository)
    reservations: ReservationRepository = field(default_factory=ReservationRepository)
    coupons: CouponRepository = field(default_factory=CouponRepository)

    @classmethod
    def seeded(cls) -> "Store":
        """A new store pre-populated with the demo data from ``app.seed``."""
        store = cls()
        load_seed(store)
        return store


def load_seed(store: Store) -> None:
    """Insert the demo data from ``app.seed`` into ``store``."""
    from app import seed

    for category in seed.CATEGORIES:
        store.categories.insert(category)
    for item in seed.ITEMS:
        store.items.insert(item)
    for customer in seed.CUSTOMERS:
        store.customers.insert(customer)
    for coupon in seed.COUPONS:
        store.coupons.insert(coupon)
    for reservation in seed.RESERVATIONS:
        store.reservations.insert(reservation)
