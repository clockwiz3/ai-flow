# Revenue report as CSV

## Motivation

Our accountant pulls the monthly revenue numbers into a spreadsheet. Right now someone copies
them by hand from the JSON of `GET /reports/revenue`. We want a CSV download of the same
report that opens directly in Excel / Google Sheets.

## Desired behaviour

A new endpoint returns the revenue report for a period as CSV. It contains exactly the same
figures as the existing JSON report for the same `start` / `end` (same rules for which
reservations count, same per-category numbers, same category order, same total).

## API contract

`GET /reports/revenue.csv?start=YYYY-MM-DD&end=YYYY-MM-DD`

Response `200`, `Content-Type: text/csv` (a `; charset=utf-8` suffix is fine). Body:

```
category,reservations,revenue
camping,1,102.00
tools,1,36.00
TOTAL,2,138.00
```

- First line is the header, exactly `category,reservations,revenue`.
- Then one line per category row of the JSON report, in the same order (alphabetical by
  category id), with the same `reservations` count and `revenue` amount. Amounts are written
  with exactly two decimals and no currency symbol or thousands separator.
- The last line is the total: `TOTAL,<sum of reservations column>,<report total>`.
- For a period without revenue the body is just the header and `TOTAL,0,0.00`.
- Lines end with a newline (`\n` or `\r\n`); no blank lines between rows.

Errors are the same as for `GET /reports/revenue`: `422` when `end` is not after `start`
(`code: "invalid_request"`) and FastAPI's default 422 when a parameter is missing or not a
date.

## Acceptance criteria

- [ ] `GET /reports/revenue.csv` returns the CSV described above.
- [ ] Numbers always match `GET /reports/revenue` for the same period.
- [ ] `GET /reports/revenue` (JSON) keeps working unchanged.
