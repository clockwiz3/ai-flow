# Refactor: service classes with constructor injection, wired through FastAPI dependencies

**Type:** refactoring (no functional change)
**Area:** `app/services/*`, `app/api/` (new `app/api/dependencies.py`), `README.md`

## Motivation

The service layer is a bag of module-level functions that all take `store` (and sometimes
`clock`) as their first arguments and call each other's modules directly
(`reservations.create_reservation(store, clock, data)` calls `catalog.get_item(store, ...)`,
`pricing.lookup_coupon(store, ...)`, ...). That makes it impossible to swap one collaborator
in a test or in another deployment without monkeypatching modules. We want proper service
objects: dependencies are passed to the constructor, and the HTTP layer obtains fully wired
services from FastAPI dependency providers that can be overridden.

## Target structure

### Service classes (exact names and constructor parameters)

Each class lives in the existing module. Constructor parameters must be exactly these, in this
order and with these names (they must also work as keyword arguments):

| Module | Class | Constructor parameters |
| --- | --- | --- |
| `app/services/catalog.py` | `CatalogService` | `store` |
| `app/services/customers.py` | `CustomerService` | `store` |
| `app/services/pricing.py` | `PricingService` | `store` |
| `app/services/availability.py` | `AvailabilityService` | `store, catalog` |
| `app/services/reservations.py` | `ReservationService` | `store, clock, catalog, customers, pricing, availability` |
| `app/services/returns.py` | `ReturnService` | `store, clock, catalog, reservations` |
| `app/services/invoices.py` | `InvoiceService` | `store, catalog, customers, pricing, reservations` |
| `app/services/reports.py` | `ReportService` | `store, invoices` |

`store` is a `Store`, `clock` a `Clock`; every other parameter is the service instance of the
same name (`catalog: CatalogService`, `customers: CustomerService`, `pricing: PricingService`,
`availability: AvailabilityService`, `reservations: ReservationService`,
`invoices: InvoiceService`).

A service must use **its injected collaborators** for anything another service owns
(e.g. `ReservationService` looks items up via `self.catalog.get_item(...)`, coupons via
`self.pricing.lookup_coupon(...)`, availability via `self.availability.ensure_available(...)`;
`ReturnService` uses its own `clock`), never by constructing other services itself.

### Methods

Every former module-level function that took `store` and/or `clock` becomes a method with the
same name and the same remaining parameters (the `store` / `clock` arguments disappear):

- `CatalogService`: `list_categories()`, `get_category(category_id)`, `get_item(item_id)`,
  `list_items(*, q=None, category=None, limit=DEFAULT_PAGE_SIZE, offset=0)`,
  `create_item(data)`, `set_item_status(item_id, status)`
- `CustomerService`: `list_customers(*, tier=None)`, `get_customer(customer_id)`,
  `create_customer(data)`
- `PricingService`: `list_coupons()`, `lookup_coupon(code)`, `get_coupon(code)`,
  `create_coupon(data)`
- `AvailabilityService`: `find_conflicts(item_id, start, end, *, exclude_id=None)`,
  `check_availability(item_id, start, end)`, `ensure_available(item, start, end)`
- `ReservationService`: `get_reservation(reservation_id)`, `list_reservations(*, customer_id=None, item_id=None, status=None)`,
  `create_reservation(data)`, `cancel_reservation(reservation_id)`
- `ReturnService`: `return_reservation(reservation_id, request)`
- `InvoiceService`: `compute_invoice(reservation)`, `get_invoice(reservation_id)`
- `ReportService`: `revenue_report(start, end)`, `utilization_report(start, end)`

**No module-level function in `app/services/` may take a `store` or `clock` parameter any
more**, and none of the names above may remain as module-level functions.

These **pure helpers stay module-level functions** with unchanged signatures (they need no
store; existing tests import some of them): in `pricing.py` `money`, `rental_days`,
`free_days`, `billable_days`, `resolve_discounts`, `quote_rental` (and the `DiscountBreakdown`
/ `RentalQuote` dataclasses); `validate_range` in `availability.py`; `late_days`, `late_rate`,
`late_fee` in `returns.py`. Module constants (`DEFAULT_PAGE_SIZE`, `MAX_PAGE_SIZE`,
`TAX_RATE`, `MAX_RENTAL_DAYS`, `LATE_FEE_MULTIPLIER`, ...) stay where they are.

### Dependency providers: `app/api/dependencies.py` (new)

This module defines these FastAPI dependency provider functions (move `get_store` /
`get_clock` here from `routes.py`; they keep reading `request.app.state.store` /
`request.app.state.clock`):

`get_store`, `get_clock`, `get_catalog_service`, `get_customer_service`,
`get_pricing_service`, `get_availability_service`, `get_reservation_service`,
`get_return_service`, `get_invoice_service`, `get_report_service`.

Each `get_*_service` provider receives **everything** it needs through `Depends(...)` on the
other providers (store via `get_store`, clock via `get_clock`, collaborating services via
their providers) and builds the service from them. Consequently overriding any provider with
FastAPI's standard mechanism, e.g.

```python
app.dependency_overrides[get_clock] = lambda: FixedClock(date(2025, 6, 10))
app.dependency_overrides[get_catalog_service] = lambda: MyCatalog(store)
```

must take effect for **every route and every service that (directly or indirectly) depends on
it** - a replaced clock changes "today" for `/health`, reservations and returns; a replaced
catalog service is the one used by `/items/...`, by availability checks and by reservation
creation. Do not cache service instances on `app.state` at start-up (that would bypass
overrides).

### Routes

- Route handlers in `app/api/` receive services (and, for `/health`, the clock) via these
  providers and call their methods. No route handler takes the store (no `store` parameter).
- Modules in `app/api/` must not import service modules or service functions: imports from
  `app.services...` are allowed only for names starting with an upper-case letter (the
  service classes and constants such as `MAX_PAGE_SIZE`), e.g.
  `from app.services.catalog import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE`. No
  `from app.services import catalog`, no `import app.services.x`.
- `create_app(store=None, clock=None)` keeps its signature and still stores them on
  `app.state.store` / `app.state.clock`.

### Docs

Update the layout table in `README.md` (service classes, `app/api/dependencies.py`).

## Constraints

- **Behaviour must not change.** Every endpoint returns exactly the same status codes,
  bodies and error messages as before for every input. This is a pure refactoring: do not
  fix or change any business logic while you are in there, even if something looks odd.
- All existing tests must keep passing **unmodified** (including `tests/conftest.py`), and
  `ruff check .` must stay clean.

## Acceptance criteria

- The eight classes exist with exactly the constructor parameters above and the listed
  methods; the old store/clock-taking module functions are gone; the pure helpers remain.
- `app/api/dependencies.py` provides the ten providers; overriding `get_clock`, `get_store`
  or any `get_*_service` via `app.dependency_overrides` affects all dependent routes and
  services.
- `app/api/` only imports upper-case names from `app.services...`; no handler takes `store`.
- The API behaves exactly as before; `pytest` and `ruff check .` pass.
