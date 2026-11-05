# handoff-demo

Constructed scenario (labelled as such in all reports): the user request names only `apply_discount`
(pricing.py); the frozen visible tests also fail for `format_money` (money.py). Provider A is expected to fix
the named behaviour and leave the other tests failing, giving repo-ai validated partial work to hand to provider B.

PROMPT: "apply_discount(cents, percent) in pricing.py must return the discounted price in whole cents,
rounding half up (for example apply_discount(1005, 50) is 503). The tests in test_pricing.py describe it."
