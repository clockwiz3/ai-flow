# Loyalty points for customers

## Background

We keep losing repeat customers to the big DIY chain down the road, which has a points
card. Our tiers (regular / silver / gold) help a bit, but they are assigned manually and most
customers never move up. Sales wants something customers can actually *see* growing with
every rental.

## What we want

Customers should collect **loyalty points** when they rent from us, and be able to
**redeem** them for a discount on future rentals.

- Customers earn points on their rentals.
- Points can be redeemed for a discount when booking.
- Staff should be able to see a customer's points balance.
- It should play nicely with the existing tier discounts and coupons.

## Notes

- Marketing would like to launch this before the summer season, so let's keep it simple.
- Finance asked that points "don't become a loophole", but we have not agreed on the
  details yet.

## Acceptance criteria

- [ ] Customers accumulate points from their rentals.
- [ ] Points can be used for a discount on a new reservation.
- [ ] The balance is visible through the API.
- [ ] Existing pricing rules keep working.
