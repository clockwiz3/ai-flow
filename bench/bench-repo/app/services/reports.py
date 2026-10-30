"""Management reports: revenue by category and item utilization."""

from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from app.models import (
    CategoryRevenue,
    ItemStatus,
    ItemUtilization,
    ReservationStatus,
    RevenueReport,
    UtilizationReport,
)
from app.services.availability import validate_range
from app.services.invoices import compute_invoice
from app.services.pricing import ZERO, money
from app.storage import Store

PERCENT_STEP = Decimal("0.1")


def revenue_report(store: Store, start: date, end: date) -> RevenueReport:
    """Net revenue (invoice total minus tax) per category.

    A reservation counts towards the period ``[start, end)`` when its start date falls in
    it. Cancelled reservations bring no revenue.
    """
    validate_range(start, end)
    revenue: dict[str, Decimal] = defaultdict(lambda: ZERO)
    counts: dict[str, int] = defaultdict(int)

    for reservation in store.reservations.all():
        if not start <= reservation.start < end:
            continue
        item = store.items.get(reservation.item_id)
        if item is None:
            continue
        invoice = compute_invoice(store, reservation)
        revenue[item.category] += invoice.total - invoice.tax
        counts[item.category] += 1

    rows = [
        CategoryRevenue(
            category=category,
            reservations=counts[category],
            revenue=money(revenue[category]),
        )
        for category in sorted(revenue)
    ]
    return RevenueReport(
        start=start,
        end=end,
        rows=rows,
        total=money(sum((row.revenue for row in rows), ZERO)),
    )


def _reserved_days(store: Store, item_id: int, start: date, end: date) -> int:
    days = 0
    for reservation in store.reservations.for_item(item_id):
        if reservation.status is ReservationStatus.CANCELLED:
            continue
        overlap = (min(reservation.end, end) - max(reservation.start, start)).days
        days += max(0, overlap)
    return days


def utilization_report(store: Store, start: date, end: date) -> UtilizationReport:
    """Share of days in ``[start, end)`` each non-retired item was reserved, in percent.

    Active and returned reservations count; cancelled ones do not.
    """
    validate_range(start, end)
    period_days = (end - start).days
    rows: list[ItemUtilization] = []
    for item in store.items.all():
        if item.status is ItemStatus.RETIRED:
            continue
        reserved = _reserved_days(store, item.id, start, end)
        pct = (Decimal(reserved) * 100 / period_days).quantize(PERCENT_STEP, rounding=ROUND_HALF_UP)
        rows.append(
            ItemUtilization(
                item_id=item.id,
                item_name=item.name,
                reserved_days=reserved,
                period_days=period_days,
                utilization_pct=pct,
            )
        )
    return UtilizationReport(start=start, end=end, rows=rows)
