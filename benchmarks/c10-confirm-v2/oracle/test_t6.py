"""Oracle for t6: `logsift.stats.bytes_by_component` and the `traffic` subcommand."""

import json
import re

LOG = """\
2026-04-09T09:00:00Z INFO cdn: GET /video/intro.mp4 200 bytes=2500000
2026-04-09T09:00:01Z INFO api: GET /v1/users 200 bytes=512
2026-04-09T09:00:02Z INFO cdn: GET /video/outro.mp4 200 bytes=1800000
2026-04-09T09:00:03Z INFO img: GET /logo.svg 200 bytes=1023
2026-04-09T09:00:04Z WARNING api: GET /v1/orders 200 bytes=361
2026-04-09T09:00:05Z INFO cdn: GET /video/trailer.mp4 206 bytes=943718
2026-04-09T09:00:06Z INFO img: GET /favicon.ico 200 bytes=1
2026-04-09T09:00:07Z INFO backup: snapshot uploaded bytes=2251799813685248
2026-04-09T09:00:08Z ERROR api: upstream reset
"""

EXPECTED = {"cdn": 5243718, "api": 873, "img": 1024, "backup": 2251799813685248}


def _log(tmp_path):
    path = tmp_path / "access.log"
    path.write_text(LOG, encoding="utf-8")
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


def test_t6_baseline_totals_per_component(tmp_path):
    from logsift.records import read_records
    from logsift.stats import bytes_by_component

    totals = dict(bytes_by_component(read_records([_log(tmp_path)])))
    assert {name: int(value) for name, value in totals.items()} == EXPECTED


def test_t6_convention_text_sizes(tmp_path, capsys):
    # rule 12: below 1024 "<n> B"; otherwise divide by 1024 until below 1024 or TiB, shown as "{:.1f} <unit>"
    code, out, _ = _run(["traffic", _log(tmp_path)], capsys)
    assert code == 0
    expected = {"api": "873 B", "img": "1.0 KiB", "cdn": "5.0 MiB", "backup": "2048.0 TiB"}
    for component, size in expected.items():
        row = _text_row(out, component)
        assert re.search(r"(?<![\w.])" + re.escape(size) + r"(?!\w)", row), row


def test_t6_convention_json_integers(tmp_path, capsys):
    # rule 12: in --format json a byte count is an integer number of bytes
    code, out, _ = _run(["traffic", _log(tmp_path), "--format", "json"], capsys)
    assert code == 0
    rows = {row["component"]: row["bytes"] for row in json.loads(out)}
    assert all(type(value) is int for value in rows.values())
    assert rows == EXPECTED
