---
name: invoicekit-conventions
description: Use when adding or changing any money, discount, tax, total or split logic in invoicekit. States the project's invoicing rules.
license: MIT
---

# invoicekit conventions

These are the rules the finance team relies on. Follow all of them in new code.

1. Amounts are integer cents everywhere. Never return or store floats.
2. Round to the cent with `decimal.ROUND_HALF_EVEN` (banker's rounding), never `round()` on floats.
3. Invalid input raises `invoicekit.errors.InvoiceError`, never `ValueError` or `TypeError`.
4. Percentages are given as numbers from 0 to 100 inclusive; anything outside that range is invalid.
5. Tax is computed and rounded **per line**, then the rounded line taxes are summed. Never compute tax on the
   invoice subtotal.
6. When an amount is split into shares, the shares are integer cents that sum exactly to the amount, and leftover
   cents go to the **earliest** shares (the first share is never smaller than a later one).
