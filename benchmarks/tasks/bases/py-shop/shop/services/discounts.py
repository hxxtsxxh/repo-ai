"""Coupons.

Fixed-amount coupons are applied first, then percentage coupons on what
is left. Every coupon is evaluated against the running subtotal.
"""

from dataclasses import dataclass

from shop.errors import ValidationError
from shop.utils.money import apply_percent

PERCENT = "percent"
FIXED = "fixed"


@dataclass(frozen=True)
class Coupon:
    code: str
    kind: str
    value: int  # percent for PERCENT coupons, cents for FIXED coupons
    min_subtotal_cents: int = 0
    active: bool = True


class CouponBook:
    def __init__(self, coupons=()):
        self._by_code = {}
        for coupon in coupons:
            self.add(coupon)

    def add(self, coupon: Coupon) -> None:
        if coupon.kind not in (PERCENT, FIXED):
            raise ValidationError(f"unknown coupon kind: {coupon.kind}")
        self._by_code[coupon.code.upper()] = coupon

    def lookup(self, code: str) -> Coupon:
        coupon = self._by_code.get(code.strip().upper())
        if coupon is None or not coupon.active:
            raise ValidationError(f"unknown or expired coupon: {code}")
        return coupon

    def discount_for(self, coupon: Coupon, subtotal_cents: int) -> int:
        if subtotal_cents < coupon.min_subtotal_cents:
            return 0
        if coupon.kind == PERCENT:
            return apply_percent(subtotal_cents, coupon.value)
        return int(coupon.value)

    def total_discount(self, codes, subtotal_cents: int) -> int:
        coupons = [self.lookup(code) for code in dict.fromkeys(codes)]
        coupons.sort(key=lambda c: 0 if c.kind == FIXED else 1)
        remaining = subtotal_cents
        total = 0
        for coupon in coupons:
            amount = self.discount_for(coupon, remaining)
            amount = min(amount, remaining)
            remaining -= amount
            total += amount
        return total
