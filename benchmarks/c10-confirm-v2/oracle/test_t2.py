"""Oracle for t2: `filter -o/--output PATH`."""

import re

LOG = """\
2026-10-11T07:15:00Z INFO billing: invoice 4411 created
2026-10-11T07:16:00Z ERROR billing: payment declined for invoice 4411
2026-10-11T07:17:00Z INFO mailer: receipt sent to björn
2026-10-11T07:18:00Z ERROR mailer: smtp timeout
"""

ERROR_LINES = [
    "2026-10-11T07:16:00Z ERROR billing: payment declined for invoice 4411",
    "2026-10-11T07:18:00Z ERROR mailer: smtp timeout",
]


def _log(tmp_path):
    path = tmp_path / "service.log"
    path.write_text(LOG, encoding="utf-8")
    return str(path)


def _run(argv, capsys):
    from logsift.cli import main

    code = main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_t2_baseline_writes_matching_lines(tmp_path, capsys):
    out_path = tmp_path / "errors.txt"
    _run(["filter", _log(tmp_path), "--level", "ERROR", "-o", str(out_path)], capsys)
    assert out_path.read_text(encoding="utf-8").splitlines() == ERROR_LINES


def test_t2_convention_refuses_existing_output(tmp_path, capsys):
    # rule 6: an existing PATH without --force fails with "<path> already exists (use --force to overwrite)",
    # returns 1 and leaves the file untouched
    out_path = tmp_path / "errors.txt"
    out_path.write_bytes(b"previous run\n")
    code, out, err = _run(["filter", _log(tmp_path), "--level", "ERROR", "-o", str(out_path)], capsys)
    assert code == 1
    assert f"{out_path} already exists (use --force to overwrite)" in err
    assert out_path.read_bytes() == b"previous run\n"


def test_t2_convention_empty_output_is_zero_bytes(tmp_path, capsys):
    # rule 6: a written file with no lines is 0 bytes
    out_path = tmp_path / "nothing.txt"
    code, out, err = _run(["filter", _log(tmp_path), "--grep", "no such text", "-o", str(out_path)], capsys)
    assert code == 0
    assert out_path.exists()
    assert out_path.read_bytes() == b""


def test_t2_convention_dry_run(tmp_path, capsys):
    # rule 7: --dry-run creates no file, prints "would write <path>" to stdout and returns 0
    out_path = tmp_path / "errors.txt"
    code, out, err = _run(
        ["filter", _log(tmp_path), "--level", "ERROR", "-o", str(out_path), "--dry-run"], capsys
    )
    assert code == 0
    assert out == f"would write {out_path}\n"
    assert not out_path.exists()
    assert "wrote" not in err


def test_t2_convention_note_on_stderr(tmp_path, capsys):
    # rule 2: the informational note is one stderr line "logsift: <message>", not starting in upper case,
    # without a trailing period, and it is not written to stdout
    out_path = tmp_path / "errors.txt"
    code, out, err = _run(["filter", _log(tmp_path), "--level", "ERROR", "-o", str(out_path)], capsys)
    assert code == 0
    lines = err.splitlines()
    assert len(lines) == 1, err
    assert re.fullmatch(r"logsift: [^A-Z\s].*[^.\s]", lines[0]), lines[0]
    assert str(out_path) not in out
