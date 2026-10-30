"""Catalog: categories and rentable items."""

from app.errors import ConflictError, InvalidRequestError, NotFoundError
from app.models import Category, Item, ItemCreate, ItemPage, ItemStatus
from app.storage import Store

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


def list_categories(store: Store) -> list[Category]:
    return store.categories.all()


def get_category(store: Store, category_id: str) -> Category:
    category = store.categories.get(category_id)
    if category is None:
        raise NotFoundError(f"Category {category_id!r} not found")
    return category


def get_item(store: Store, item_id: int) -> Item:
    item = store.items.get(item_id)
    if item is None:
        raise NotFoundError(f"Item {item_id} not found")
    return item


def _matches(item: Item, q: str | None, category: str | None) -> bool:
    if category is not None and item.category != category:
        return False
    if q:
        return q.strip() in item.name
    return True


def list_items(
    store: Store,
    *,
    q: str | None = None,
    category: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> ItemPage:
    """Search the catalog.

    ``q`` filters by item name, ``category`` by category id. Results are ordered by item id;
    ``offset`` items are skipped and at most ``limit`` returned. ``total`` is the number of
    matching items before pagination.
    """
    if not 1 <= limit <= MAX_PAGE_SIZE:
        raise InvalidRequestError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
    if offset < 0:
        raise InvalidRequestError("offset must not be negative")

    matching = [item for item in store.items.all() if _matches(item, q, category)]
    return ItemPage(
        items=matching[offset:limit],
        total=len(matching),
        limit=limit,
        offset=offset,
    )


def create_item(store: Store, data: ItemCreate) -> Item:
    """Add a new item to the catalog. The category must already exist."""
    if data.category not in store.categories:
        raise InvalidRequestError(f"Unknown category {data.category!r}")
    return store.items.create(data)


def set_item_status(store: Store, item_id: int, status: ItemStatus) -> Item:
    """Move an item between available / maintenance / retired.

    Retiring is permanent: a retired item cannot be brought back.
    """
    item = get_item(store, item_id)
    if item.status is ItemStatus.RETIRED and status is not ItemStatus.RETIRED:
        raise ConflictError(f"Item {item_id} is retired and cannot change status")
    return store.items.save(item.model_copy(update={"status": status}))
