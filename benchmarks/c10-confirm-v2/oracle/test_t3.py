"""Oracle for t3: `summary --skip-invalid`."""

import json

FIRST = """\
2026-06-20T11:00:00Z INFO worker: job 7 started
this line is garbage
2026-06-20T11:01:00Z ERROR worker: job 7 failed
2026-06-20T11:02:00Z SEVERE worker: unknown level here

2026-06-20T11:03:00Z INFO scheduler: tick
"""

SECOND = """\
@@ truncated @@
2026-06-20T11:04:00Z ERROR scheduler: missed tick
"""


def _files(tmp_path):
    first = tmp_path / "first.log"
    second = tmp_path / "second.log"
    first.write_text(FIRST, encoding="utf-8")
    second.write_text(SECOND, encoding="utf-8")
    return str(first), str(second)


def _run(argv, capsys):
    from logsift.cli import main

    code = main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_t3_baseline_counts_valid_records(tmp_path, capsys):
    first, second = _files(tmp_path)
    _, out, _ = _run(["summary", first, second, "--skip-invalid", "--format", "json"], capsys)
    counts = {row["level"]: int(row["count"]) for row in json.loads(out)}
    assert counts == {"INFO": 2, "ERROR": 2}


def test_t3_convention_exit_code_when_skipped(tmp_path, capsys):
    # rule 5: main returns 3 instead of 0 when at least one line was skipped
    first, second = _files(tmp_path)
    code, _, _ = _run(["summary", first, second, "--skip-invalid"], capsys)
    assert code == 3


def test_t3_convention_warning_lines(tmp_path, capsys):
    # rule 5: one "logsift: warning: <path>:<lineno>: skipped unparseable line" per skipped line,
    # path as given, line numbers from 1, input order; blank lines are not reported
    first, second = _files(tmp_path)
    _, _, err = _run(["summary", first, second, "--skip-invalid"], capsys)
    warnings = [line for line in err.splitlines() if line.startswith("logsift: warning: ")]
    assert warnings == [
        f"logsift: warning: {first}:2: skipped unparseable line",
        f"logsift: warning: {first}:4: skipped unparseable line",
        f"logsift: warning: {second}:1: skipped unparseable line",
    ]


def test_t3_convention_quiet_suppresses_warnings(tmp_path, capsys):
    # rule 3: top-level --quiet suppresses the warnings on stderr; stdout is unchanged
    first, second = _files(tmp_path)
    _, loud_out, _ = _run(["summary", first, second, "--skip-invalid"], capsys)
    _, quiet_out, quiet_err = _run(["--quiet", "summary", first, second, "--skip-invalid"], capsys)
    assert quiet_err == ""
    assert quiet_out == loud_out
    assert "INFO" in quiet_out
