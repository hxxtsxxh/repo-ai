# Author A notes

Project: `stockroom`, an in-memory stock ledger (items, receive/issue movements,
reorder checks, valuation, text report). Skill: `skill/stockroom-conventions/`.

| Rule | Inferable from code? | Why |
|---|---|---|
| 1 | yes | `unit_cost_cents`, `item_value_cents`, `total_value_cents` are all ints with the `_cents` suffix. |
| 2 | yes | `normalize_sku` in `skus.py` does strip/upper plus the regex, and every entry point calls it. |
| 3 | yes | `quantities.require_positive_quantity` holds the exact check and message. |
| 4 | yes | `errors.py` defines the hierarchy and the exact messages, and tests assert them. |
| 5 | yes | `items()`, `below_reorder_point()` and `stock_lines()` return SKU-sorted tuples; `history()` returns tuples in recorded order. |
| 6 | no | No code divides money; the rounding mode (HALF_EVEN) and the use of Decimal appear nowhere. |
| 7 | no | No ranking function exists; the descending-metric order and the SKU tie-break are unstated. |
| 8 | no | No averages or ratios exist; returning `None` (rather than 0 or raising) on empty input is unstated. |
| 9 | no | No percentages exist; the Decimal type, 0-100 scale, one decimal place and HALF_UP are all unstated. |
| 10 | no | No period filtering exists; the half-open interval, `InvalidPeriodError` and its message appear nowhere. |
| 11 | no | Timestamps are stored but never rendered; the format, Z suffix and truncation are unstated. |
| 12 | no | All operations change one line; the all-or-nothing and first-failing-line rules are never exercised. |
| 13 | no | The code generates no IDs; the prefix, 6-digit padding and per-prefix counter starting at 1 appear nowhere. |
| 14 | no | The code has no logging at all; the logger convention, the WARNING level and the message format are unstated. |

Total: 14 rules. 9 are not inferable (6-14) and 5 are inferable (1-5).

## Visible tests

Command (run from `fixture/`):

    cd fixture && python3 -m pytest -q

Output:

    .........................                                                [100%]
    25 passed in 0.01s
