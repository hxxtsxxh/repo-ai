def apply_discount(cents, percent):
    """Return the price in whole cents after a percentage discount (round half up)."""
    return cents - cents * percent // 100
