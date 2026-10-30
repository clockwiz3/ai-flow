# Invoices with a coupon show the wrong discount and tax

**Reported by:** accounting (Marek)
**Severity:** high - invoices with coupons don't match our pricing rules; the tax we report is wrong

## What happens

When a reservation has a coupon, the invoice takes the coupon off the amount **after** tax
has been added, and it also ends up discounting the late fee. Our pricing rules (README,
"Pricing" and "Invoices") say:

- tier discount and coupon **add up** into one combined rate (capped at 30%),
- the combined discount applies **only to the rental amount**,
- discounts are applied **before tax**, and tax is 20% of `subtotal - discount`.

Invoices without a coupon look correct.

## Example

Silver customer Bob (customer 2) books the Family Tent (item 6, 35.00/day) for 5 days with
coupon `SPRING10`:

```
POST /reservations
{"item_id": 6, "customer_id": 2, "start": "2025-06-20", "end": "2025-06-25", "coupon_code": "SPRING10"}

GET /reservations/{id}/invoice
```

| field    | actual  | expected |
| -------- | ------- | -------- |
| subtotal | 175.00  | 175.00   |
| discount | 28.70   | 26.25    |
| tax      | 33.25   | 29.75    |
| total    | 179.55  | 178.50   |

(5% silver + 10% coupon = 15% of 175.00 = 26.25; tax = 20% of 148.75 = 29.75.)

## Acceptance criteria

- Invoice `discount`, `tax` and `total` follow the README for every combination of tier and
  coupon.
- The coupon never reduces the late-fee line; only the rental amount is discounted.
- Invoices without a coupon are unchanged.
- The revenue report (which is based on invoices) reflects the corrected figures.
