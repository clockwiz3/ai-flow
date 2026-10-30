# Searching the catalog for "tent" finds nothing

**Reported by:** web shop team
**Severity:** medium - most customers type in lower case and get empty results

## What happens

The `q` parameter of `GET /items` only matches when the search text has exactly the same
upper/lower case as the item name. The README says the search is a case-insensitive
substring match on the item name.

## Example (demo data)

```
GET /items?q=tent
```

- **Actual:** `"items": []`, `"total": 0`
- **Expected:** Two-Person Tent (id 5) and Family Tent (id 6), `"total": 2`

`GET /items?q=Tent` works today and must keep working; `q=TENT` or `q=fAmIlY` should also
find the tents.

## Acceptance criteria

- `q` matches item names case-insensitively as a substring, in combination with the
  `category` filter and pagination.
- `total` reflects the case-insensitive matches.
- Searching for text that is not in any item name still returns an empty list.
