# Reviewer C: assertion review

test_t1_baseline_counts_per_component | KEEP | The request names the columns and asks for JSON "in the same way as summary does" (an array of objects keyed by header), and the per-component counts on whole-second records involve no convention.
test_t1_convention_text_timestamps | KEEP | Rule 10 alone fixes UTC "YYYY-MM-DD HH:MM:SS" with the fraction dropped and no zone, so the api row must show 2026-08-14 21:07:33 and 2026-08-15 23:10:40 (first/last are the same in input and time order).
test_t1_convention_text_duration | KEEP | Rule 11 alone fixes unpadded hours and truncated seconds, and 93787.65 s gives 26:03:07 whether computed from exact or from truncated timestamps.
test_t1_convention_json_timestamps | KEEP | Rule 10 alone fixes the JSON form "YYYY-MM-DDTHH:MM:SSZ" in UTC with the fraction dropped, and the keys first/last are the requested column names.
test_t1_convention_json_duration | KEEP | Rule 11 alone fixes an integer number of truncated seconds, 93787, under either way of computing the span.
test_t2_baseline_writes_matching_lines | KEEP | Writing the two ERROR lines to a fresh PATH is the requested behaviour and the line-by-line comparison ignores newline details decided by rule 6.
test_t2_convention_refuses_existing_output | KEEP | Rule 6 alone says a subcommand with -o/--output fails on an existing PATH without --force with the exact message, returns 1 and leaves the file untouched.
test_t2_convention_empty_output_is_zero_bytes | KEEP | Rule 6 states that a written file with no lines is 0 bytes, and the request says the matching lines (here none) are written to PATH with filter otherwise unchanged (exit 0).
test_t2_convention_dry_run | KEEP | Rule 7 alone makes every subcommand that writes a file accept --dry-run, print exactly "would write <path>" with the path as given, create nothing, print no "wrote" message and return 0.
test_t2_convention_note_on_stderr | KEEP | Rule 2 alone puts the requested note on stderr as one line "logsift: <message>" that does not start in upper case and has no trailing period, and the regex accepts any wording.
test_t3_baseline_counts_valid_records | DELETE | It parses stdout as JSON, so it depends on the skip notices not going to stdout; the request leaves open how "the user is told" (rule 5 decides stderr), and a reasonable implementation that prints a notice on stdout would fail.
test_t3_convention_exit_code_when_skipped | KEEP | Rule 5 alone says main returns 3 instead of 0 when at least one line was skipped.
test_t3_convention_warning_lines | KEEP | Rule 5 alone gives the exact warning text, the path as given, line numbers from 1, input order and no warning for blank lines; the SEVERE line is unparseable by the project's parser, as the baseline also assumes.
test_t3_convention_quiet_suppresses_warnings | DELETE | The fixture has no -q/--quiet option, so the assertion needs an unrequested new top-level option; rule 3 can reasonably be read as describing that option's behaviour rather than requiring this task to add it.
test_t4_baseline_reads_config_file | KEEP | Reading ignore from the config file with an empty environ is the requested behaviour, and the comparison is order-insensitive.
test_t4_convention_env_list_parsing | KEEP | Rule 13 alone gives the variable name LOGSIFT_IGNORE and comma-splitting with items stripped and empty items dropped, which yields auth and queue.
test_t4_convention_env_beats_config | KEEP | Rule 13's "first source that provides it wins" (environment before config file) alone gives ['auth'], and the request's "set the ignore list through an environment variable" is consistent with replacement.
test_t4_convention_empty_env_is_unset | KEEP | Rule 13 alone says an empty environment variable counts as unset, so the config file's ['queue'] applies.
test_t5_baseline_shows_version | KEEP | Showing logsift.__version__ on stdout or stderr is the requested behaviour, and any stream is accepted.
test_t5_convention_version_output | KEEP | Rule 4 alone fixes stdout "logsift <version>\n" from logsift.__version__, an empty stderr and return 0.
test_t6_baseline_totals_per_component | KEEP | Summing the bytes=<n> values per component through the requested function involves no convention.
test_t6_convention_text_sizes | KEEP | Rule 12 alone gives 873 B, 1.0 KiB, 5.0 MiB and 2048.0 TiB (division stops at TiB) for these totals.
test_t6_convention_json_integers | KEEP | Rule 12 alone says a byte count in JSON output is an integer number of bytes, and the keys are the requested column names.
test_t7_baseline_counts_per_file | KEEP | The per-file counts with the path as given are the requested output, and the parsing ignores row order and column alignment.
test_t7_convention_order_ties_by_code_point | KEEP | The sources rows carry a count, so rule 8 alone orders them by count and breaks ties by case-sensitive code-point order of the path, giving Z.log, a.log, m.log.
test_t7_convention_json_format | KEEP | Rule 9 alone requires --format text/json on a report-printing subcommand and fixes the exact json.dumps call, the lower-case header keys and integer counts, and the expected row order is the same under count order and input order.
test_t7_convention_off_switch_has_no_positive_form | KEEP | Rule 14 alone says the off switch is a store_true --no-header with no positive --header, so --header is an argparse usage error returning 2 (rule 1).
test_t8_baseline_reads_names | KEEP | Stripping names, skipping blank and comment lines and keeping file order are all specified in the request.
test_t8_convention_missing_file_error | KEEP | Rule 1 alone says an OSError from file I/O is re-raised as LogsiftError (or a subclass) with the message "cannot read <path>: <strerror>".

## Leaks

LEAK | test_t3_convention_warning_lines | the request says "the user is told about every line that was skipped", which gives away the one-report-per-skipped-line structure the assertion checks; the request could simply have said that the user is told lines were skipped

## Counts

- Test functions reviewed: 29
- KEEP: 27 (baseline 7, convention 20)
- DELETE: 2 (baseline 1, convention 1)
- LEAK: 1
