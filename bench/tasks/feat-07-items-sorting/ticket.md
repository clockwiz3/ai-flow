# Sort the catalog by name or daily rate

## Motivation

The new web shop front-end shows the catalog with a "Sort by" drop-down ("Name A-Z",
"Price: low to high", "Price: high to low"). The front-end currently downloads the whole
catalog and sorts it in the browser, which breaks as soon as pagination is used. The API
should do the sorting.

## Desired behaviour

`GET /items` gets two new optional query parameters:

| Parameter | Values | Default |
| --- | --- | --- |
| `sort` | `id`, `name`, `daily_rate` | `id` |
| `order` | `asc`, `desc` | `asc` |

- `sort=name` orders alphabetically by item name, **case-insensitively**.
- `sort=daily_rate` orders by the numeric daily rate (`6.50` comes before `12.00`).
- `sort=id` (the default) is the current behaviour: ordered by item id.
- `order=desc` reverses the direction of the chosen sort key (`order=desc` without `sort`
  lists items by id descending).
- Ties (same name or same daily rate) are always broken by item id **ascending**, in both
  directions.
- Sorting is applied to the matching items (after the `q` / `category` filters) and
  **before** pagination, so `limit=3&sort=daily_rate&order=desc` returns the three most
  expensive matching items. `total` is unchanged by sorting.
- Without `sort` / `order` the response is exactly the same as today.

## Errors

Any other value for `sort` or `order` is rejected with `422` (FastAPI's default validation
error is fine).

## Acceptance criteria

- [ ] `GET /items?sort=name`, `?sort=daily_rate`, with `order=asc|desc`, return items in the
      described order.
- [ ] Sorting combines with `q`, `category`, `limit` and `offset`.
- [ ] Invalid `sort` / `order` values return 422.
- [ ] Default behaviour unchanged.
