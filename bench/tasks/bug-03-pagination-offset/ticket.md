# Catalog page 2 is empty

**Reported by:** web shop team
**Severity:** medium - customers can only ever see the first page of the catalog

## What happens

`GET /items` paginates incorrectly as soon as `offset` is non-zero. Asking for the second
page returns nothing (or too few items), even though `total` says there are more.

## Example (demo data, 12 items with ids 1-12)

```
GET /items?limit=5&offset=5
```

- **Actual:** `"items": []`, `"total": 12`
- **Expected:** items with ids `6, 7, 8, 9, 10`, `"total": 12`, `"limit": 5`, `"offset": 5`

```
GET /items?limit=3&offset=2
```

- **Actual:** only item `3`
- **Expected:** items `3, 4, 5`

## Acceptance criteria

- Pagination works as described in the README: skip `offset` matching items, then return
  at most `limit` items, ordered by id. `total` is the number of matching items before
  pagination.
- Works together with the `category` / `q` filters.
- An offset beyond the end returns an empty page (not an error).
