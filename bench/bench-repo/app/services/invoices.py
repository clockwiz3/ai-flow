"""Invoices for reservations.

An invoice has a rental line and, for late returns, a late-fee line. Discounts apply to the
rental line only; tax is charged on the discounted subtotal.
"""

from decimal import Decimal

from app.errors import ConflictError
from app.models import Invoice, InvoiceLine, InvoiceLineKind, Reservation, ReservationStatus
from app.services.catalog import get_item
from app.services.customers import get_customer
from app.services.pricing import TAX_RATE, ZERO, lookup_coupon, money, quote_rental
from app.services.reservations import get_reservation
from app.services.returns import late_days, late_fee, late_rate
from app.storage import Store


def _late_fee_line(reservation: Reservation, daily_rate: Decimal) -> InvoiceLine | None:
    if reservation.returned_on is None:
        return None
    days_late = late_days(reservation.end, reservation.returned_on)
    if days_late == 0:
        return None
    return InvoiceLine(
        kind=InvoiceLineKind.LATE_FEE,
        description=f"Late return ({days_late} day{'s' if days_late != 1 else ''})",
        quantity=days_late,
        unit_price=late_rate(daily_rate),
        amount=late_fee(daily_rate, days_late),
    )


def compute_invoice(store: Store, reservation: Reservation) -> Invoice:
    """Build the invoice for ``reservation`` regardless of its status."""
    item = get_item(store, reservation.item_id)
    customer = get_customer(store, reservation.customer_id)
    coupon = lookup_coupon(store, reservation.coupon_code) if reservation.coupon_code else None
    quote = quote_rental(item, customer, reservation.start, reservation.end, coupon)

    free_note = f", {quote.free_days} free" if quote.free_days else ""
    lines = [
        InvoiceLine(
            kind=InvoiceLineKind.RENTAL,
            description=f"{item.name} rental ({quote.days} days{free_note})",
            quantity=quote.billable_days,
            unit_price=item.daily_rate,
            amount=quote.rental_amount,
        )
    ]
    late_line = _late_fee_line(reservation, item.daily_rate)
    if late_line is not None:
        lines.append(late_line)

    subtotal = sum((line.amount for line in lines), ZERO)

    tier_discount = money(quote.rental_amount * quote.discounts.tier_rate)
    taxable = subtotal - tier_discount
    tax = money(taxable * TAX_RATE)
    coupon_discount = money((taxable + tax) * quote.discounts.coupon_rate)

    return Invoice(
        reservation_id=reservation.id,
        customer_id=customer.id,
        lines=lines,
        subtotal=money(subtotal),
        discount=tier_discount + coupon_discount,
        tax=tax,
        total=money(taxable + tax - coupon_discount),
    )


def get_invoice(store: Store, reservation_id: int) -> Invoice:
    """Invoice of an active or returned reservation; cancelled ones are not billed."""
    reservation = get_reservation(store, reservation_id)
    if reservation.status is ReservationStatus.CANCELLED:
        raise ConflictError(f"Reservation {reservation_id} is cancelled and has no invoice")
    return compute_invoice(store, reservation)
