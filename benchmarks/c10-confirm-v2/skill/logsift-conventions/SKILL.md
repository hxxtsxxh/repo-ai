---
name: logsift-conventions
description: Holds the coding conventions of the logsift project; use it whenever changing or adding code to the logsift package.
---

# logsift conventions

`logsift` is a command-line tool that summarizes, filters and exports application log files. These conventions
apply to every change in the `logsift` package and its tests. Follow them exactly: where a rule gives a message
text, a format or a name, match it character for character.

1. **Failures and exit codes.** `main` returns 0 on success, 1 for a run-time failure and 2 for a command-line usage
   error; it never calls `sys.exit` and never lets `SystemExit` escape. Usage errors (unknown options, missing
   arguments, invalid option values) are detected by argparse, with value checks done by `type=` functions that
   raise `argparse.ArgumentTypeError`, and `main` returns argparse's exit code. Run-time failures are raised by the
   functions that do the work as `LogsiftError` or one of its subclasses from `logsift.errors`; those functions
   never print or exit. An `OSError` from file I/O is re-raised as `LogsiftError` with the message
   `cannot read <path>: <strerror>` or `cannot write <path>: <strerror>`. `main` catches `LogsiftError`, writes
   exactly one line `logsift: error: <message>` to stderr, writes nothing to stdout, and returns 1.
2. **stdout and stderr.** stdout carries only the result of a command (a report, matching lines, JSON).
   Informational messages, such as which file was written, go to stderr as one line `logsift: <message>`, starting
   in lower case and without a trailing period, for example `logsift: wrote 3 records to out.jsonl`.
3. **Quiet mode.** The top-level parser has the option `-q`/`--quiet`, given before the subcommand
   (`logsift --quiet export ...`). It suppresses every informational message (rule 2) and every warning (rule 5)
   on stderr. Error lines (rule 1), everything written to stdout, files written and exit codes are unchanged.
4. **Version.** `logsift --version` writes `logsift <version>` followed by a newline to stdout, where `<version>`
   is the value of `logsift.__version__`; it writes nothing to stderr, and `main` returns 0.
5. **Unparseable lines.** A subcommand continues past unparseable log lines only when given its own option
   `--skip-invalid` (on the subcommand, not the top-level parser). Each skipped line produces one stderr line
   `logsift: warning: <path>:<lineno>: skipped unparseable line`, with the path as given on the command line,
   line numbers counted from 1, in input order. The remaining records are processed as usual, and `main` returns 3
   instead of 0 when at least one line was skipped. Blank lines are still ignored and are not counted as skipped.
   Without `--skip-invalid`, an unparseable line remains a run-time failure (rule 1).
6. **Output files.** Files are written with `logsift.output.write_text`: UTF-8 without a byte-order mark, `\n` line
   endings, every line including the last ending in `\n` (a file with no lines is 0 bytes). A subcommand that writes
   a file takes `-o`/`--output PATH` and `--force`. If `PATH` exists and `--force` is not given, it fails with
   `OutputExistsError`, whose message is `<path> already exists (use --force to overwrite)`, returns 1, and leaves
   the existing file untouched.
7. **Dry run.** A subcommand that writes files accepts `--dry-run`. With it, the subcommand reads and validates
   everything as usual and fails with the same errors and exit codes (including the existing-file check of rule 6),
   but creates or changes no file. For each file it would have written it prints `would write <path>` to stdout,
   one line per file in the order they would be written, with the path as given on the command line. It prints no
   `wrote ...` informational message and returns 0 on success.
8. **Report order.** Report rows that carry a count are ordered by count, highest first; rows with equal counts are
   ordered by the value of their first column in ascending code-point order (plain, case-sensitive `str`
   ordering). Text and JSON output use the same order.
9. **JSON output.** A subcommand that prints a report takes `--format` with the choices `text` and `json`, default
   `text`. JSON output is `json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)` followed by one `\n`
   (`logsift.render.render_json`). A report of rows is a JSON array of objects whose keys are exactly the lower-case
   column headers of the text table; counts are JSON integers.
10. **Timestamps.** A timestamp shown in text output is the UTC time formatted as `YYYY-MM-DD HH:MM:SS`: a space
    between date and time, fractional seconds dropped, no zone suffix (for example `2026-01-31 23:05:09`). In
    `--format json` output a timestamp is the UTC time as a string `YYYY-MM-DDTHH:MM:SSZ`, fractional seconds
    dropped.
11. **Durations.** A duration shown in text output is `H:MM:SS`: whole hours without padding (may exceed 24), then
    minutes and seconds as two digits each; fractional seconds are dropped, not rounded (3725.9 seconds is
    `1:02:05`). In `--format json` output a duration is an integer number of seconds, truncated the same way.
12. **Byte sizes.** A byte count shown in text output is `<n> B` when it is below 1024. Otherwise it is divided by
    1024 until the value is below 1024 or the unit reaches TiB, and shown as `f"{value:.1f}"` followed by a space
    and the unit `KiB`, `MiB`, `GiB` or `TiB` (1536 bytes is `1.5 KiB`). In `--format json` output a byte count is
    an integer number of bytes.
13. **Settings precedence.** When a setting can come from more than one source, the first source that provides it
    wins, in this order: command-line option, environment variable, config file (`--config`), built-in default.
    The environment variable for the config key `<key>` is `LOGSIFT_` followed by the key in upper case (key
    `max_width` is `LOGSIFT_MAX_WIDTH`). An environment variable set to the empty string counts as unset. A
    list-valued setting in an environment variable is comma-separated; each item is stripped of surrounding
    whitespace and empty items are dropped. An invalid value in an environment variable is a run-time failure
    (rule 1) with the message `LOGSIFT_<KEY>: invalid value '<value>'`.
14. **Off switches.** An option that turns off something a subcommand does by default is a `store_true` flag named
    `--no-<thing>`, where `<thing>` is the noun for the behaviour that is turned off (for example `--no-wrap`). It
    has no short form and no positive `--<thing>` counterpart.
