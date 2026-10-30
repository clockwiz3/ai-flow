# Customers returning on the due date get charged a late day

**Reported by:** customer support
**Severity:** medium - several complaints and manual refunds this week

## What happens

A customer who brings an item back on the reservation's `end` date - which is exactly when
it is due back - is charged one day of late fee. Every late return also seems to be billed
one day more than it should be.

Per the README, returning on the `end` date (or earlier) is on time (0 late days), returning
on `end + 1` is 1 late day, and the late fee is `daily_rate * 1.5 * late_days`.

## Example (demo data)

Reservation 4: Circular Saw (item 2, 18.00/day), 2025-06-01 to 2025-06-04, regular customer.
On 2025-06-04 the customer returns it:

```
POST /reservations/4/return
{"returned_on": "2025-06-04"}
```

- **Actual:** `"late_days": 1`, `"late_fee": "27.00"`, and the invoice
  (`GET /reservations/4/invoice`) contains a `late_fee` line; total `97.20`.
- **Expected:** `"late_days": 0`, `"late_fee": "0.00"`, invoice has only the rental line;
  subtotal `54.00`, tax `10.80`, total `64.80`.

Returning on 2025-06-06 should be 2 late days (fee `54.00`), but we currently charge 3.

## Acceptance criteria

- Return receipts and invoices compute late days as described in the README.
- On-time and early returns have no late fee and no `late_fee` invoice line.
