"""Customer accounts."""

from app.errors import ConflictError, NotFoundError
from app.models import Customer, CustomerCreate, CustomerTier
from app.storage import Store


def list_customers(store: Store, *, tier: CustomerTier | None = None) -> list[Customer]:
    customers = store.customers.all()
    if tier is not None:
        customers = [c for c in customers if c.tier is tier]
    return customers


def get_customer(store: Store, customer_id: int) -> Customer:
    customer = store.customers.get(customer_id)
    if customer is None:
        raise NotFoundError(f"Customer {customer_id} not found")
    return customer


def create_customer(store: Store, data: CustomerCreate) -> Customer:
    """Register a customer. E-mail addresses are unique (case-insensitive)."""
    if store.customers.by_email(data.email) is not None:
        raise ConflictError(f"A customer with e-mail {data.email!r} already exists")
    return store.customers.create(data)
