# Reject discounts outside 0-100

`rental_price` accepts any `discount_pct`. A discount of 120 produces a negative price and -10 makes the
rental more expensive. Raise `ValueError` when `discount_pct` is below 0 or above 100. Discounts of exactly
0 and 100 stay valid.
