---
name: stockroom-conventions
description: Holds the coding conventions of the stockroom inventory-ledger project; use it whenever changing or adding code to the stockroom package.
---

# stockroom coding conventions

Follow every rule below when you add or change code in the `stockroom` package.
"Public" means any function, method or class not prefixed with `_`.

1. **Money is integer cents.** Every monetary amount is an `int` number of cents
   (never `float`, never `Decimal`) and every field, parameter or function that
   holds or returns money has a name ending in `_cents` (e.g. `unit_cost_cents`,
   `total_value_cents`).

2. **SKUs.** Every public entry point that accepts a SKU passes it through
   `stockroom.skus.normalize_sku` (strip whitespace, upper-case) before use. A
   valid SKU is exactly three letters A-Z, a hyphen, and four digits
   (`^[A-Z]{3}-\d{4}$`); anything else raises `InvalidSkuError`.

3. **Quantities.** Unit quantities passed into an operation are positive `int`s,
   validated with `stockroom.quantities.require_positive_quantity`. Zero,
   negatives, non-ints and `bool` raise `InvalidQuantityError` with the message
   `quantity must be a positive integer, got <repr(qty)>`.

4. **Error types and messages.** Every exception the package raises on purpose is
   a subclass of `StockroomError` (`TypeError` for passing a wrong object type is
   the only exception). A missing SKU raises `UnknownSkuError` with message
   `unknown SKU: <SKU>`; taking more than is on hand raises
   `InsufficientStockError` with message
   `insufficient stock for <SKU>: requested <n>, on hand <m>`.

5. **Collections are sorted tuples.** A public function that returns several
   records returns a `tuple` (never a `list`, set or generator). Records keyed by
   item are sorted by SKU ascending (plain string order) unless rule 7 applies;
   movements are returned in the order they were recorded.

6. **Rounding money division.** Whenever money is divided (averages, per-unit
   cost, splitting an amount), the result is rounded to a whole number of cents
   with `decimal.ROUND_HALF_EVEN` (banker's rounding): 250 cents / 100 units ->
   2 cents, 350 / 100 -> 4 cents, 1 cent / 2 -> 0 cents. Compute with
   `decimal.Decimal`, never with float division.

7. **Rankings and tie-breaking.** A function that returns items ranked by a
   numeric metric (e.g. "top movers", "most valuable") sorts by the metric
   descending, and breaks ties by SKU ascending.

8. **Empty input for averages and ratios.** An average or ratio computed over
   zero records (no items, no movements, zero denominator) returns `None`. It
   never raises and never returns `0`.

9. **Percentages.** Ratios presented as percentages (fill rate, share of value,
   etc.) are returned as `decimal.Decimal` on a 0-100 scale quantized to exactly
   one decimal place with `decimal.ROUND_HALF_UP`: 2 of 3 -> `Decimal("66.7")`,
   1 of 8 -> `Decimal("12.5")`, 1 of 1 -> `Decimal("100.0")`.

10. **Time periods are half-open.** Any filter or report over a time period takes
    `start` and `end` datetimes and includes a movement when
    `start <= movement.at < end` (start inclusive, end exclusive). If
    `start >= end`, raise `InvalidPeriodError` (define it in `stockroom/errors.py`
    as a subclass of both `StockroomError` and `ValueError`) with the message
    `period start must be before end`.

11. **Rendering timestamps.** When a timestamp is rendered as text, convert it to
    UTC and format it as ISO 8601 with second precision and a literal `Z` suffix,
    dropping (truncating, not rounding) any microseconds:
    `2024-03-01T09:30:00Z`. Use `dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")`.

12. **Multi-line operations are all-or-nothing.** An operation that applies
    several stock changes at once (a batch issue, a transfer, a stock count) first
    validates every line; if any line would fail, it raises that line's error
    (the first failing line, in input order) and changes nothing: on-hand levels
    and history are exactly as before the call.

13. **Generated identifiers.** Identifiers the package generates (transfer IDs,
    count IDs, batch IDs, ...) have the form `<PREFIX>-<n>`, where `PREFIX` is
    three upper-case letters chosen per record type (e.g. `TRF`) and `n` is a
    sequence number zero-padded to 6 digits. Each `Inventory` instance keeps a
    separate counter per prefix starting at 1: the first transfer of a new
    inventory is `TRF-000001`, the second `TRF-000002`.

14. **Logging non-issue stock removals.** Each module that logs uses
    `logger = logging.getLogger(__name__)` (so records fall under the
    `stockroom` logger hierarchy); never `print`. Every operation that reduces
    on-hand stock for any reason other than a plain `issue` (write-offs,
    negative adjustments, damage, transfers out) emits exactly one `WARNING`
    record per affected SKU with the message `<reason> <qty> x <SKU>`, e.g.
    `write_off 3 x BLT-0001`, where `<reason>` is the movement's reason string
    and `<qty>` is the positive number of units removed. Ordinary `receive` and
    `issue` do not log.
