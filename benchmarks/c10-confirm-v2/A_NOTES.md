# A_NOTES

**logsift**: a command-line log-file summarizer that counts, filters, ranks and exports lines of application logs (`<ISO timestamp> <LEVEL> <component>: <message>`), with an optional TOML config.

Package `logsift` has 10 modules: `__init__`, `__main__`, `cli`, `errors`, `records`, `filters`, `stats`, `render`, `output`, `config`. It has 4 subcommands: `summary`, `filter`, `top`, `export`.

| Rule | Inferable from code? | Why |
|---|---|---|
| 1. Failures and exit codes (0/1/2, argparse `type=` checks, `LogsiftError` raised by the work functions, `cannot read/write <path>: <strerror>`, one `logsift: error: <message>` line) | yes | `cli.main` catches `SystemExit` from `parse_args` and returns its code, then catches `LogsiftError` and prints `logsift: error: ...` and returns 1. `_level`/`_positive_int` raise `ArgumentTypeError`. `records.read_records`, `output.write_text` and `config.load_config` wrap `OSError` as `cannot read/write <path>: <strerror>`. Tests cover exits 1 and 2 and the exact stderr lines. |
| 2. stdout carries only results; informational messages go to stderr as `logsift: <message>` | yes | `cli._info` prints `logsift: wrote N records to PATH` to stderr. Reports and filtered lines go to stdout. `test_export_writes_jsonl` checks that stdout is empty and checks the stderr text. |
| 3. `-q/--quiet` top-level option suppresses info and warnings | no | The CLI has no quiet option and no way to suppress messages. `_info` always prints. Nothing tells you whether such an option would be top-level or per subcommand, or what it would leave alone. |
| 4. `--version` prints `logsift <version>` to stdout and returns 0 | no | There is no `--version` option. `__version__` exists only as the ordinary package attribute (it matches `pyproject.toml`) and nothing uses it. The output format and which stream it goes to are not shown anywhere. |
| 5. `--skip-invalid` per subcommand, warning text, exit code 3 | no | The code always treats an unparseable line as a fatal `ParseError` (exit 1). It has no skipping, no warning messages, no `warning:` prefix and no exit code 3. The error text it does use (`cannot parse <path> line <n>: '<line>'`) has a different layout from the warning. |
| 6. Output files: `write_text`, UTF-8 without BOM, `\n` endings, final newline, `-o/--output` + `--force`, `OutputExistsError` message | yes | `output.write_text` opens the file with `encoding="utf-8", newline="\n"`, adds a missing final newline and raises `OutputExistsError` (`<path> already exists (use --force to overwrite)`). `export` has `-o/--output` and `--force`. Tests check the bytes and the refusal. |
| 7. `--dry-run` validates, writes nothing, prints `would write <path>` to stdout, exit 0 | no | No subcommand has a dry-run mode, and no code or test mentions previewing writes. |
| 8. Report order: count descending, then first column ascending by code point | yes | `stats.sort_counts` sorts by `(-count, key)`. `count_by` and `top_messages` use it for both text and JSON. Tests check the tie order (`CRITICAL`, `DEBUG`, `WARNING`; `ok` before `pool size #`). |
| 9. `--format text\|json` (default text), `json.dumps(indent=2, sort_keys=True, ensure_ascii=False)` + `\n`, rows as objects keyed by the lower-case headers | yes | `summary` and `top` have `--format`. `render.render_json` and `rows_to_objects` produce exactly this, and `test_render_json_is_sorted_and_indented` checks the exact string. |
| 10. Timestamps: text `YYYY-MM-DD HH:MM:SS` UTC; `--format json` `YYYY-MM-DDTHH:MM:SSZ` | no | No text or `--format json` output contains a timestamp. `filter` prints raw input lines verbatim. The only formatted time is in `export` files, which use `isoformat()` (`+00:00`). That format differs from the rule, so it cannot be copied from there. |
| 11. Durations: text `H:MM:SS` (truncated); JSON integer seconds | no | The code computes and shows no durations at all. |
| 12. Byte sizes: `<n> B`, otherwise `f"{value:.1f}"` + `KiB`/`MiB`/`GiB`/`TiB`; JSON integer bytes | no | The code computes and shows no sizes. The `export` message reports a record count, not bytes. |
| 13. Settings precedence: option > environment variable > config > default; `LOGSIFT_<KEY>`; empty means unset; comma lists; `LOGSIFT_<KEY>: invalid value '<value>'` | no | The code reads no environment variables. The only config setting (`ignore`) has no matching command-line option, so no setting has two sources. The order, the variable names, the list syntax and the error text are all invisible. |
| 14. Off switches are `store_true` flags named `--no-<thing>`, no short form, no positive counterpart | no | Every existing flag turns something on (`--force`) or takes a value. No option disables a default behaviour, so there is no naming precedent. |

**Totals:** 14 rules. 5 are inferable (1, 2, 6, 8, 9) and 9 are not inferable (3, 4, 5, 7, 10, 11, 12, 13, 14). None is on the c10-confirm-v1 topics.

**Hint check:** after the final edits I searched `logsift/`, `tests/` and `pyproject.toml` for `quiet`, `version`, `skip`, `warning:`, `dry`, `would`, `environ`, `getenv`, `LOGSIFT_`, `--no-`, `strftime`, `KiB`, `duration`, `seconds`, `isatty` and `tty`. The only matches were:
- the `__version__` attribute and the pyproject `version` (see rule 4);
- `total_seconds()` in a test of UTC conversion.

I renamed one test from `..._skips_blank_lines_...` to `..._ignores_blank_lines_...` so that it does not echo rule 5's wording.

**Visible test run:**

```
$ cd fixture && python3 -m pytest -q
............................................                             [100%]
44 passed in 0.08s
```
