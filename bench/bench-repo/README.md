# Rentwise

Rentwise is the back-office API of a small equipment rental shop: power tools, camping gear,
photo equipment and garden machines. It is a FastAPI service with in-memory storage, seeded
with demo data on start-up.

This README is the **specification**. Where the code and this document disagree, the code
is wrong.

## Running

```sh
pytest -q          # tests
ruff check .       # lint
```

`app.main:create_app(store=None, clock=None)` builds an application. By default it uses a
freshly seeded `Store` and the system clock; tests inject a `FixedClock` pinned to
2025-06-02 (`app.seed.SEED_TODAY`).

## Layout

| Path | Purpose |
| --- | --- |
| `app/models.py` | Pydantic models and enums |
| `app/storage.py` | In-memory repositories, `Store`, seed loader |
| `app/seed.py` | Demo data |
| `app/clock.py` | Injectable "today" |
| `app/errors.py` | Domain exceptions -> HTTP errors |
| `app/services/` | Business rules (catalog, customers, availability, pricing, reservations, returns, invoices, reports) |
| `app/api/routes.py` | All HTTP routes |

## Domain rules

### Dates

All date ranges are **half-open** `[start, end)`. A reservation's `end` is exclusive: the
item is back in the shop on the morning of `end`. So a reservation ending on day X and
another starting on day X for the same item do **not** overlap and are both allowed.
The number of rental days is `end - start`.

### Items

An item has `id`, `name`, `category` (a category id), `daily_rate`, `deposit` (money) and
`status`: `available`, `maintenance` or `retired`.

- Only `available` items can be reserved.
- Retiring an item is permanent; a retired item cannot change status again.
- New items must reference an existing category; `daily_rate` must be positive.

### Catalog search

`GET /items` lists items ordered by id.

- `q`: case-insensitive substring match on the item name (`"tent"` finds
  "Two-Person Tent" and "Family Tent").
- `category`: exact category id.
- Pagination: first skip `offset` matching items, then return at most `limit` items
  (`limit` 1..100, default 20; `offset` >= 0, default 0). `total` is the number of
  matching items before pagination.

### Customers

A customer has `id`, `name`, `email` (unique, case-insensitive, stored lower-case) and
`tier`: `regular`, `silver` or `gold`.

### Reservations

A reservation has `item_id`, `customer_id`, `start`, `end`, optional `coupon_code` and
`status`: `active`, `cancelled` or `returned`.

- `end` must be after `start`; a reservation may last at most 90 days.
- `start` may not be in the past (today is allowed).
- The item and customer must exist; an unknown coupon code is rejected (422).
- The item must be `available`.
- **An item cannot have overlapping active reservations.** Two ranges overlap when they
  share at least one day, i.e. `a.start < b.end and b.start < a.end`. This includes a new
  range that starts inside, ends inside, exactly matches, or fully contains an existing one.
- **Only `active` reservations block an item.** Cancelled and returned reservations never
  affect availability.
- Only `active` reservations can be cancelled or returned.

`GET /availability?item_id&start&end` answers whether a reservation for that range would be
accepted, with a reason and the ids of the conflicting reservations.

### Pricing

- `days = end - start`. One day is free for every **full** 7 days:
  `billable_days = days - days // 7` (7 days -> 6 billable, 14 -> 12).
- Rental amount = `daily_rate * billable_days`.
- Tier discount: regular 0%, silver 5%, gold 15%.
- Coupons (`POST /coupons`): an upper-case alphanumeric code with a percent off (1..100).
- Tier and coupon discounts **add up** (silver 5% + 10% coupon = 15%) and the combined
  discount is **capped at 30%** (gold 15% + 20% coupon = 30%, not 35%).
- Discounts apply **only to the rental amount** and are applied **before tax**.
- Tax is 20% of the discounted subtotal.

### Returns

`POST /reservations/{id}/return` with optional `returned_on` (defaults to today) and
`damaged` flag.

- `returned_on` cannot be before `start` or after today.
- `late_days = max(0, returned_on - end)`. Returning on the `end` date (or earlier) is on
  time: 0 late days. Returning on `end + 1` is 1 late day.
- Late fee = `daily_rate * 1.5 * late_days`.
- Damaged: the whole deposit is withheld and the item goes to `maintenance`. Otherwise the
  deposit is refunded in full.
- Early returns are not refunded: the rental is charged for the booked range.

### Invoices

`GET /reservations/{id}/invoice` (active or returned reservations; cancelled ones have no
invoice, 409).

- Lines: a `rental` line (quantity = billable days) and, for late returns, a `late_fee`
  line (quantity = late days).
- `subtotal` = sum of line amounts.
- `discount` = rental line amount * combined discount rate (tier + coupon, capped at 30%).
- `tax` = 20% of `subtotal - discount`.
- `total` = `subtotal - discount + tax`.
- Money is a decimal, rounded to 0.01 with ROUND_HALF_UP only when a figure is produced
  (each line amount, discount, tax, total) - never on intermediate rates.

Example: gold customer, Family Tent (35.00/day), 5 days: subtotal 175.00, discount 26.25,
tax 29.75, total 178.50.

### Reports

- `GET /reports/revenue?start&end`: net revenue (invoice total minus tax) per category for
  reservations whose `start` falls in `[start, end)`. **Cancelled reservations are
  excluded**; active and returned ones count.
- `GET /reports/utilization?start&end`: for every non-retired item, the number of days in
  `[start, end)` covered by active or returned reservations and that as a percentage of the
  period (one decimal, half up). Cancelled reservations do not count.

## API

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/health` | status and current date |
| GET | `/categories` | |
| GET | `/items` | `q`, `category`, `limit`, `offset` |
| POST | `/items` | 201 |
| GET | `/items/{id}` | |
| POST | `/items/{id}/status` | `{"status": ...}` |
| GET | `/customers` | `tier` filter |
| POST | `/customers` | 201, 409 on duplicate e-mail |
| GET | `/customers/{id}` | |
| GET | `/coupons` | |
| POST | `/coupons` | 201, 409 on duplicate code |
| GET | `/availability` | `item_id`, `start`, `end` |
| GET | `/reservations` | `customer_id`, `item_id`, `status` filters |
| POST | `/reservations` | 201 |
| GET | `/reservations/{id}` | |
| POST | `/reservations/{id}/cancel` | |
| POST | `/reservations/{id}/return` | body optional |
| GET | `/reservations/{id}/invoice` | |
| GET | `/reports/revenue` | `start`, `end` |
| GET | `/reports/utilization` | `start`, `end` |

Errors are JSON `{"detail": "...", "code": "not_found" | "conflict" | "invalid_request"}`
with status 404 / 409 / 422 respectively (request validation errors use FastAPI's default
422 body).
