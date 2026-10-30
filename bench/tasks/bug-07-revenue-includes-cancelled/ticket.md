# Revenue report includes cancelled bookings

**Reported by:** finance (Marek)
**Severity:** high - monthly revenue figures are inflated

## What happens

`GET /reports/revenue` adds cancelled reservations to the revenue and to the reservation
count of their category. Cancelled bookings were never billed (they have no invoice), so
they must not show up in revenue. Per the README, cancelled reservations are excluded;
active and returned ones count.

## Example (demo data)

```
GET /reports/revenue?start=2025-05-01&end=2025-06-10
```

Actual:

```json
{"rows": [
  {"category": "camping", "reservations": 1, "revenue": "102.00"},
  {"category": "photo",   "reservations": 2, "revenue": "213.75"},
  {"category": "tools",   "reservations": 2, "revenue": "90.00"}
 ], "total": "405.75"}
```

Both photo reservations in that period (ids 3 and 6) are cancelled. Expected:

```json
{"rows": [
  {"category": "camping", "reservations": 1, "revenue": "102.00"},
  {"category": "tools",   "reservations": 2, "revenue": "90.00"}
 ], "total": "192.00"}
```

A category whose only reservations in the period are cancelled should not appear at all
(same as a category with no reservations).

## Acceptance criteria

- Cancelled reservations contribute neither revenue nor a reservation count, including
  reservations cancelled through `POST /reservations/{id}/cancel`.
- Active and returned reservations are still counted as before.
- The utilization report is not affected.
