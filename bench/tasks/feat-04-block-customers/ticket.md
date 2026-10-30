# Block customers from making new reservations

## Motivation

Every now and then a customer stops paying invoices or repeatedly returns gear in bad shape.
The front desk needs a way to stop such a customer from booking anything new until the
situation is sorted out, without deleting the account or touching their existing bookings.

## Desired behaviour

- Staff can **block** and **unblock** any customer.
- A blocked customer cannot create new reservations. The request is refused with
  `403 Forbidden` and a clear error message saying the customer is blocked.
- Blocking does not affect anything else: existing reservations stay as they are and can
  still be cancelled, returned and invoiced; the customer still shows up in listings.
- Unblocking restores normal behaviour immediately.
- Blocking an already blocked customer (or unblocking a non-blocked one) is not an error; the
  call simply returns the customer in the requested state.

## API contract

### `POST /customers/{id}/block` and `POST /customers/{id}/unblock`

No request body. Response `200`: the customer, e.g.

```json
{"id": 1, "name": "Alice Martin", "email": "alice@example.com", "tier": "regular", "blocked": true}
```

`404` (`code: "not_found"`) for an unknown customer.

### Customer representation

Every customer returned by the API (`GET /customers`, `GET /customers/{id}`,
`POST /customers`, block / unblock) gains a boolean field `blocked`. New customers start
with `blocked: false`; it cannot be set through `POST /customers`.

### `POST /reservations`

If the customer exists and is blocked, respond with:

- status `403`
- body `{"detail": "<message mentioning that the customer is blocked>", "code": "forbidden"}`

An unknown customer is still `404`, as today. No reservation is created when the request is
refused.

## Acceptance criteria

- [ ] Block / unblock endpoints work for every customer and return the updated customer.
- [ ] `blocked` is part of the customer representation everywhere.
- [ ] Blocked customers get `403` with `code: "forbidden"` on `POST /reservations`.
- [ ] Existing reservations of a blocked customer are unaffected.
- [ ] Existing behaviour and tests are otherwise unaffected.
