from invoicekit.errors import InvoiceError


def line_total(qty, unit_cents):
    """Total for one invoice line, in integer cents."""
    if qty < 0:
        raise InvoiceError("quantity must not be negative")
    return int(qty) * int(unit_cents)
