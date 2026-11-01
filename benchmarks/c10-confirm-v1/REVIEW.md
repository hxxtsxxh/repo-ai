# Reviewer C: assertion review

test_t1_baseline_write_off_reduces_stock | KEEP | The request fully specifies the return value, the on-hand effect and the movement's (sku, -qty, "write_off", at), and the test checks nothing else.
test_t1_convention_logs_one_warning | KEEP | Rule 14 names write-offs, the WARNING level, the `<reason> <qty> x <SKU>` text and a `getLogger(__name__)` logger, and the request gives the reason string, so "write_off 3 x BLT-0001" under a stockroom.* logger is the only answer.
test_t1_convention_insufficient_stock_error | KEEP | The request forbids writing off more than is on hand, and rule 4 fixes both the exception type and the exact message for that case.
test_t1_convention_invalid_quantity | KEEP | The request forbids nonsensical quantities, and rule 3 fixes InvalidQuantityError with the exact message for qty 0.
test_t2_baseline_issue_many_issues_every_line | KEEP | It checks only on-hand levels and the issue movements recorded in line order, which the request states explicitly.
test_t2_convention_failed_batch_changes_nothing | KEEP | Rule 12 names batch issues and requires no change to levels or history, and the raised InsufficientStockError comes from the requested "exactly like issue" semantics.
test_t2_convention_first_failing_line_wins | KEEP | Rule 12 says the first failing line in input order raises, the only failing lines are ZZZ-9999 (unknown, line 2) and NUT 999 (line 3), and rule 4 makes the unknown SKU an UnknownSkuError.
test_t2_convention_batch_ids | KEEP | The request supplies the prefix BAT, and rule 13 fixes the 6-digit padding and a per-instance counter that starts at 1.
test_t3_baseline_count_sets_levels | KEEP | It checks the requested final levels and the count_adjust deltas without caring about order (the list is sorted), and the unchanged SKU gets no movement, as the request says.
test_t3_convention_shrinkage_logs_warning | KEEP | Rule 14 explicitly covers negative adjustments, the request gives the reason "count_adjust", and the only shrinking SKU is BLT, so "count_adjust 4 x BLT-0001" is the only answer.
test_t3_convention_bad_line_changes_nothing | KEEP | Rule 12 explicitly lists a stock count, rule 4 fixes UnknownSkuError for the unregistered SKU, and ZZZ-9999 is the only failing line.
test_t3_convention_count_ids | KEEP | The request says each call returns a count identifier with prefix CNT, even when nothing changes, and rule 13 fixes CNT-000001, CNT-000002 and a fresh counter per instance.
test_t4_baseline_weighted_average | KEEP | Both cases divide exactly (60/20 and 900/30), so any correct implementation passes with ==, whether it returns int, float or Decimal and however it rounds.
test_t4_convention_half_even_rounding | KEEP | The only money division is total value divided by total units, and rule 6 fixes ROUND_HALF_EVEN with these exact examples (250/100 -> 2, 350/100 -> 4).
test_t4_convention_no_stock_returns_none | KEEP | Rule 8 says an average with zero units in the denominator returns None, and both test cases have zero units.
test_t4_convention_result_is_int_cents | KEEP | Rule 1 says money is an int number of cents, never float or Decimal, and the request's function name already ends in _cents.
test_t5_baseline_share_of_value | KEEP | 25 and 75 are exact for int, float or Decimal, with or without rounding, on the 0-100 scale the request shows by example.
test_t5_convention_percentage_format | KEEP | Rule 9 fixes the Decimal type, the 0-100 scale, exactly one decimal place and ROUND_HALF_UP, so 6.25 -> "6.3" and 1 of 1 -> "100.0" are the only answers.
test_t5_convention_zero_total_returns_none | KEEP | Rule 8 says a ratio with a zero denominator returns None, and the total value here is 0.
test_t6_baseline_filters_by_period | KEEP | No movement sits on a boundary and recorded order equals timestamp order, so any inclusive or exclusive reading and any reasonable ordering pass.
test_t6_convention_half_open_period | KEEP | Rule 10 states start <= at < end exactly, so including the start movement and excluding the end movement is the only answer.
test_t6_convention_invalid_period | KEEP | Rule 10 fixes the class name, its module (stockroom/errors.py), both base classes, the start >= end trigger and the exact message.
test_t6_convention_tuple_in_recorded_order | KEEP | Rule 5 says several records come back as a tuple and movements in the order recorded, and Movement objects are plainly records.
test_t7_baseline_line_fields | KEEP | rsplit(" ", 3) reads only the SKU, the explicitly signed delta and the reason, so it works with any timestamp format; recorded order equals timestamp order, and list() accepts any iterable.
test_t7_convention_timestamp_rendering | KEEP | Rule 11 fixes UTC conversion, second precision, truncated microseconds and the Z suffix, and the request fixes the rest of the line, so "2024-03-01T09:30:15Z BLT-0001 +5 receive" is the only answer.
test_t7_convention_tuple_in_recorded_order | DELETE | Rule 5 covers functions that return "several records", and whether rendered text lines count as records is open to a second reading (an agent can reasonably return a list of strings), so the isinstance(tuple) check does not follow from the rule text alone.
test_t8_baseline_ranks_by_units_issued | KEEP | It has no ties and no boundary timestamps, units are positive "units removed" as the request says, and tuple(p) accepts any pair type.
test_t8_convention_ties_broken_by_sku | KEEP | Rule 7 fixes metric descending with ties broken by SKU ascending, giving PIN, then BLT, NUT, WSH.
test_t8_convention_half_open_period | KEEP | Rule 10 states start <= at < end exactly, so the issue at START is counted and the issue at END is excluded.
test_t8_convention_returns_tuple | KEEP | The (sku, units_issued) pairs are records keyed by item, and rule 5 says such collections are returned as a tuple.

## Leaky requests

- t5 (minor): the example "an item holding a quarter of the stock value gives 25" gives away rule 9's 0-100 scale. It does not give away the Decimal type, the one-decimal quantization or ROUND_HALF_UP, which are what test_t5_convention_percentage_format actually tests.
- t6 (very minor): "optionally restricted to one SKU like `Inventory.history`" points the agent at a method that returns a tuple in recorded order, a mild hint toward rule 5. It states no ordering or type, so it is not a leak strictly speaking.
- Not leaks: t2 and t3 name the ID prefixes BAT and CNT, but rule 13 leaves the prefix to be chosen per record type, so the request must supply it. Neither request reveals the padding or the counter behaviour.

## Counts

- Test functions reviewed: 30
- KEEP: 29 (baseline 8, convention 21)
- DELETE: 1 (convention 1): test_t7_convention_tuple_in_recorded_order
