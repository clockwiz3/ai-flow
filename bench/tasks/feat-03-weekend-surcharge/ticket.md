# Weekend surcharge per category

## Motivation

Cameras and tents are in high demand on weekends and we keep running out of them, while
they sit on the shelf from Monday to Friday. Management wants to charge a **weekend
surcharge** for some categories: every Saturday and Sunday inside a rental costs a
configurable percentage of the item's daily rate on top of the normal price. The percentage
is set per category by staff and may change over time, but a customer must always pay what
was in force when they booked.

## Desired behaviour

### Configuring the surcharge

- Every category has a `weekend_surcharge_pct`: an integer between `0` and `100`
  (inclusive). All existing categories start at `0` (no surcharge).
- Staff read and change it through the pricing endpoints below.

### Snapshot on the reservation

- When a reservation is created, it records the `weekend_surcharge_pct` of its item's
  category **at that moment**. Every reservation returned by the API gains this integer
  field `weekend_surcharge_pct`. Seeded reservations have `0`.
- Invoices (and therefore reports) always use the reservation's recorded percentage, never
  the category's current one. Changing a category's surcharge only affects reservations
  created afterwards.

### Which days are surcharged

- The rental days of a reservation are the dates `start, start + 1, ..., end - 1` (`end`
  is exclusive, as everywhere else). Day number 1 is `start`.
- The free-day rule is unchanged (`billable_days = days - days // 7`), and it now also
  says **which** days are free: the 7th, 14th, 21st, ... day of the rental (day numbers
  divisible by 7). A free day is completely free: neither its daily rate nor any surcharge
  is charged.
- A **surcharged day** is a rental day that falls on a Saturday or a Sunday and is not a
  free day.

### Invoice

- When the reservation's recorded percentage is above 0 and it has at least one surcharged
  day, the invoice gets an extra line:
  - `kind`: `"weekend_surcharge"`
  - `quantity`: the number of surcharged days
  - `unit_price`: `daily_rate * pct / 100`, **not rounded** (e.g. `0.975`), like the
    late-fee line's unit price
  - `amount`: `daily_rate * pct / 100 * quantity`, rounded once to 0.01 (half up)
  - `description`: free text
- Otherwise there is no surcharge line (never a line with quantity 0 or amount 0).
- Line order: `rental`, then `weekend_surcharge` (if any), then `late_fee` (if any).
- The `rental` line is unchanged.
- Discounts: the combined tier + coupon rate (capped at 30%, as today) now applies to the
  **rental line plus the surcharge line**: `discount = (rental amount + surcharge amount) *
  rate`, rounded to 0.01 half up. The late fee is still never discounted.
- Late fees are unchanged: `daily_rate * 1.5` per late day, no surcharge on late days.
- `subtotal`, `tax` (20% of `subtotal - discount`) and `total` follow the existing rules,
  with the surcharge line included in the subtotal.

### Reports

- The revenue report is computed from invoices, so a category's revenue includes its
  surcharges (net of discount). The shape of the report does not change.

## Worked examples

Today is Monday 2025-06-02.

**1.** Photo surcharge set to 20%. Gold customer (15%) books the Mirrorless Camera
(45.00/day) from Sunday 2025-06-08 to 2025-06-16 with coupon `WELCOME20` (20%).

- 8 rental days, Sun 06-08 ... Sun 06-15. Day 7 is Saturday 06-14: free.
- Billable days: 8 - 1 = 7, rental line 7 x 45.00 = 315.00.
- Weekend days: 06-08, 06-14, 06-15; 06-14 is free, so 2 surcharged days.
  Surcharge line: quantity 2, unit price 9.00, amount 18.00.
- Subtotal 333.00. Discount rate 15% + 20% = 35%, capped at 30%: 333.00 x 0.30 = 99.90.
- Tax 20% of 233.10 = 46.62. Total 279.72.

**2.** Camping surcharge set to 15%. Silver customer (5%) books the Camping Stove
(6.50/day) from Saturday 2025-06-07 to 2025-06-15.

- 8 rental days; day 7 is Friday 06-13 (free). Rental line 7 x 6.50 = 45.50.
- Surcharged days: 06-07, 06-08, 06-14 = 3. Unit price 0.975, amount 2.925 -> 2.93.
- Subtotal 48.43, discount 48.43 x 0.05 = 2.4215 -> 2.42, tax 46.01 x 0.20 = 9.202 ->
  9.20, total 55.21.

## API contract

### `GET /categories/{id}/pricing`

Response `200`:

```json
{"category": "photo", "weekend_surcharge_pct": 20}
```

`404` (`code: "not_found"`) for an unknown category.

### `PUT /categories/{id}/pricing`

Request:

```json
{"weekend_surcharge_pct": 20}
```

Response `200`: same shape as the `GET`, with the new value.

| Situation | Status | `code` |
| --- | --- | --- |
| Unknown category | 404 | `not_found` |
| Missing value, not an integer, below 0 or above 100 | 422 | (FastAPI validation error) |

A rejected request changes nothing.

### Other representations

- `GET /categories`: every category gains `weekend_surcharge_pct`.
- Every reservation (list, get, create, cancel) gains `weekend_surcharge_pct`.
- Invoice lines may have `kind: "weekend_surcharge"`.

## Acceptance criteria

- [ ] Surcharge can be read and set per category, with validation as above.
- [ ] Reservations record the percentage in force when they were created.
- [ ] Invoices contain the surcharge line and apply the free-day, discount, cap, tax and
      rounding rules above.
- [ ] The revenue report reflects surcharges.
- [ ] Existing behaviour and tests are otherwise unaffected.
