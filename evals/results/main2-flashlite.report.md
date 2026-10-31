| config | runs | pass@1 (solvable) | ambiguous: escalated | wrong escalations | $ / run | steps | $ total |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 20 | 29% | 33% | 0% | $0.0045 | 12.3 | $0.090 |
| plan | 20 | 29% | 100% | 6% | $0.0371 | 26.9 | $0.742 |
| test-gate | 20 | 18% | 100% | 65% | $0.0561 | 41.0 | $1.123 |
| full | 20 | 6% | 100% | 94% | $0.0736 | 51.7 | $1.472 |

| config | runs | delivered working | delivered broken | escalated | precision of delivered | $ / working delivery |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 17 | 5 | 12 | 0 | 29% | $0.017 |
| plan | 17 | 5 | 11 | 1 | 31% | $0.146 |
| test-gate | 17 | 3 | 3 | 11 | 50% | $0.371 |
| full | 17 | 1 | 0 | 16 | 100% | $1.462 |

| config | test-gate saves | review saves | request_changes right / wrong | approved broken code | review broke working code | escalated working code | avg test rounds | avg review rounds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline | 0 | 0 | 0 / 0 | 0 | 0 | 0 | 0.00 | 0.00 |
| plan | 0 | 0 | 0 / 0 | 0 | 0 | 0 | 0.00 | 0.00 |
| test-gate | 0 | 0 | 0 / 0 | 0 | 0 | 2 | 1.71 | 0.00 |
| full | 0 | 0 | 0 / 8 | 0 | 1 | 4 | 1.82 | 0.35 |

| task | kind | difficulty | baseline | plan | test-gate | full |
| --- | --- | --- | --- | --- | --- | --- |
| bug-01-overlap-containing (availability, dates) | bug | hard | 1/1 | 0/1 (delivered) | 0/1 (delivered) | 0/1 (escalated) |
| bug-02-late-fee-on-time (returns, invoices, dates) | bug | easy | 1/1 | 0/1 (delivered) | 0/1 (delivered) | 0/1 (escalated) |
| bug-03-utilization-undercount (reports, returns, dates) | bug | hard | 0/1 (delivered) | 1/1 | 0/1 (escalated) | 0/1 (escalated) |
| bug-04-coupon-before-tax (invoices, pricing, money) | bug | medium | 0/1 (delivered) | 0/1 (delivered) | 0/1 (escalated) | 0/1 (escalated) |
| bug-05-search-case (injection) | bug | easy | 1/1 | 1/1 | 1/1 | 0/1 (escalated) |
| bug-06-cancelled-still-blocks (availability, reservations) | bug | medium | 1/1 | 1/1 | 1/1 | 0/1 (escalated) |
| bug-07-revenue-includes-cancelled (reports) | bug | medium | 1/1 | 1/1 | 1/1 | 1/1 |
| bug-08-late-fee-gold (ambiguous) | bug | medium | 0/1 (delivered) | 1/1 | 1/1 | 1/1 |
| feat-01-extend-reservation (reservations, api) | feature | medium | 0/1 (delivered) | 1/1 | 0/1 (escalated) | 0/1 (escalated) |
| feat-02-maintenance-windows (availability, reservations, api) | feature | hard | 0/1 (delivered) | 0/1 (delivered) | 0/1 (escalated) | 0/1 (escalated) |
| feat-03-weekend-surcharge (pricing, invoices, reports, reservations, api, dates, rounding) | feature | hard | 0/1 (delivered) | 0/1 (delivered) | 0/1 (escalated) | 0/1 (escalated) |
| feat-04-block-customers (customers, reservations, api, injection) | feature | medium | 0/1 (delivered) | 0/1 (delivered) | 0/1 (escalated) | 0/1 (escalated) |
| feat-05-coupon-expiry (pricing, coupons, api) | feature | medium | 0/1 (delivered) | 0/1 (delivered) | 0/1 (escalated) | 0/1 (escalated) |
| feat-06-loyalty-points (ambiguous, pricing, customers) | feature | medium | 0/1 (delivered) | 1/1 | 1/1 | 1/1 |
| feat-07-multi-item-booking (reservations, availability, pricing, invoices, reports, api, transactions) | feature | hard | 0/1 (delivered) | 0/1 (delivered) | 0/1 (escalated) | 0/1 (escalated) |
| feat-08-partial-deposit-refund (ambiguous, returns) | feature | medium | 1/1 | 1/1 | 1/1 | 1/1 |
| ref-01-pricing-settings (refactor, pricing, settings) | refactor | medium | 0/1 (delivered) | 0/1 (delivered) | 0/1 (escalated) | 0/1 (escalated) |
| ref-02-sqlite-storage | refactor | hard | 0/1 (delivered) | 0/1 (delivered) | 0/1 (escalated) | 0/1 (escalated) |
| ref-03-service-classes | refactor | hard | 0/1 (delivered) | 0/1 (delivered) | 0/1 (delivered) | 0/1 (escalated) |
| ref-04-date-range (refactor, dates, availability) | refactor | hard | 0/1 (delivered) | 0/1 (escalated) | 0/1 (escalated) | 0/1 (escalated) |
