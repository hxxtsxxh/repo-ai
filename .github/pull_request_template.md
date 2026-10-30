## What and why

<!-- One coherent change. Link the issue if there is one. -->

## Evidence

<!-- Commands you ran and their results (paste the summary lines). -->
- [ ] `ruff check src tests benchmarks/run.py scripts` and `mypy`
- [ ] `python scripts/build_plugin.py --check` and `python scripts/gen_cli_reference.py --check`
- [ ] tests: <!-- which, and how many passed/failed/skipped -->
- [ ] bug fix: the new regression test fails on the old code

## Claims check

- [ ] No output, doc or log line claims more than the code observed (PASS ≠ correct)
- [ ] No new network or model call on an offline/dry-run path
- [ ] `CHANGELOG.md` / `docs/STATUS.md` updated if behaviour or a capability status changed
