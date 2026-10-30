# Coupon invoices don't reconcile with the pricing policy

**Reported by:** finance (Marek)
**Severity:** high - the VAT we declare is computed from these invoices

## What we noticed

During the monthly reconciliation, invoices for reservations booked with a coupon don't
match the pricing policy (README, "Pricing" and "Invoices"). Invoices without a coupon
reconcile fine. We checked a handful by hand; here is one we can reproduce on the demo data.

Silver customer Bob (customer 2) books the Family Tent (item 6, 35.00/day) for 5 days with
coupon `SPRING10`:

```
POST /reservations
{"item_id": 6, "customer_id": 2, "start": "2025-06-20", "end": "2025-06-25", "coupon_code": "SPRING10"}

GET /reservations/{id}/invoice
```

The invoice we get:

| field    | amount  |
| -------- | ------- |
| subtotal | 175.00  |
| discount | 28.70   |
| tax      | 33.25   |
| total    | 179.55  |

None of discount, tax or total is what the policy gives for this booking, and the figures
are not even consistent with each other: 20% of `175.00 - 28.70` is not `33.25`.

We have not yet checked invoices that combine a coupon with a late return, but we'd like
those to be right too.

## Expected

- Invoice figures (`discount`, `tax`, `total`) for any reservation follow the README pricing
  and invoice rules, for every combination of customer tier and coupon, with or without a
  late return.
- Invoices that were already correct stay unchanged.
- Reports built from invoice figures reflect the corrected amounts.
