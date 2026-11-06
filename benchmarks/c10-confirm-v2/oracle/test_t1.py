"""Oracle for t1: the `span` subcommand."""

import json
import re

SPAN_LOG = """\
2026-08-14T22:37:33.250+01:30 INFO api: request served
2026-08-15T03:00:00Z DEBUG cache: warm
2026-08-15T05:30:00Z INFO cache: evicted 12 keys
2026-08-15T23:10:40.900Z WARNING api: slow response
"""

PLAIN_LOG = """\
2026-09-02T08:00:00Z INFO queue: started
2026-09-02T08:00:10Z INFO auth: login ok
2026-09-02T08:00:20Z WARNING queue: backlog growing
2026-09-02T08:00:30Z ERROR queue: consumer died
"""


def _write(tmp_path, name, text):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def _run(argv, capsys):
    from logsift.cli import main

    code = main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _text_row(out, component):
    for line in out.splitlines():
        parts = line.split()
        if parts and parts[0] == component:
            return line
    raise AssertionError(f"no row for {component!r} in:\n{out}")


def _json_rows(out):
    return {row["component"]: row for row in json.loads(out)}


def test_t1_baseline_counts_per_component(tmp_path, capsys):
    log = _write(tmp_path, "plain.log", PLAIN_LOG)
    code, out, _ = _run(["span", log, "--format", "json"], capsys)
    rows = _json_rows(out)
    assert {name: int(row["count"]) for name, row in rows.items()} == {"queue": 3, "auth": 1}


def test_t1_convention_text_timestamps(tmp_path, capsys):
    # rule 10: text timestamps are UTC "YYYY-MM-DD HH:MM:SS", fractional seconds dropped, no zone suffix
    log = _write(tmp_path, "span.log", SPAN_LOG)
    code, out, _ = _run(["span", log], capsys)
    assert code == 0
    row = _text_row(out, "api")
    assert re.search(r"(?<![\dT:-])2026-08-14 21:07:33(?![\d.:Z+])", row), row
    assert re.search(r"(?<![\dT:-])2026-08-15 23:10:40(?![\d.:Z+])", row), row


def test_t1_convention_text_duration(tmp_path, capsys):
    # rule 11: text duration is H:MM:SS, hours unpadded and may exceed 24, fraction truncated
    # (93787.65 seconds -> 26:03:07)
    log = _write(tmp_path, "span.log", SPAN_LOG)
    code, out, _ = _run(["span", log], capsys)
    assert code == 0
    row = _text_row(out, "api")
    assert re.search(r"(?<![\d:])26:03:07(?![\d.:])", row), row


def test_t1_convention_json_timestamps(tmp_path, capsys):
    # rule 10: JSON timestamps are UTC strings "YYYY-MM-DDTHH:MM:SSZ", fractional seconds dropped
    log = _write(tmp_path, "span.log", SPAN_LOG)
    code, out, _ = _run(["span", log, "--format", "json"], capsys)
    assert code == 0
    api = _json_rows(out)["api"]
    assert api["first"] == "2026-08-14T21:07:33Z"
    assert api["last"] == "2026-08-15T23:10:40Z"


def test_t1_convention_json_duration(tmp_path, capsys):
    # rule 11: JSON duration is an integer number of seconds, truncated (93787.65 -> 93787)
    log = _write(tmp_path, "span.log", SPAN_LOG)
    code, out, _ = _run(["span", log, "--format", "json"], capsys)
    assert code == 0
    duration = _json_rows(out)["api"]["duration"]
    assert type(duration) is int
    assert duration == 93787
