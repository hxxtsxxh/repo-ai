"""Oracle for t7: the `sources` subcommand."""

import json


def _write(path, count):
    lines = [f"2026-05-17T1{i}:00:00Z INFO relay: hop {i}\n" for i in range(count)]
    path.write_text("".join(lines), encoding="utf-8")
    return str(path)


def _run(argv, capsys):
    from logsift.cli import main

    code = main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_t7_baseline_counts_per_file(tmp_path, capsys):
    north = _write(tmp_path / "north.log", 4)
    south = _write(tmp_path / "south.log", 2)
    _, out, _ = _run(["sources", north, south], capsys)
    counts = {}
    for line in out.splitlines():
        for path in (north, south):
            if path in line:
                counts[path] = int(line.replace(path, "").split()[-1])
    assert counts == {north: 4, south: 2}


def test_t7_convention_order_ties_by_code_point(tmp_path, capsys):
    # rule 8: highest count first; equal counts by first column in case-sensitive code-point order
    middle = _write(tmp_path / "m.log", 2)
    lower = _write(tmp_path / "a.log", 3)
    upper = _write(tmp_path / "Z.log", 3)
    code, out, _ = _run(["sources", middle, lower, upper], capsys)
    assert code == 0
    order = [path for line in out.splitlines() for path in (middle, lower, upper) if line.split()[:1] == [path]]
    assert order == [upper, lower, middle]


def test_t7_convention_json_format(tmp_path, capsys):
    # rule 9: --format json prints json.dumps(rows, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
    # an array of objects keyed by the lower-case headers, counts as integers
    big = _write(tmp_path / "überblick.log", 3)
    small = _write(tmp_path / "rest.log", 1)
    code, out, _ = _run(["sources", big, small, "--format", "json"], capsys)
    assert code == 0
    expected = [{"file": big, "count": 3}, {"file": small, "count": 1}]
    assert out == json.dumps(expected, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def test_t7_convention_off_switch_has_no_positive_form(tmp_path, capsys):
    # rule 14: the off switch is a plain --no-<thing> flag with no positive --<thing> counterpart
    path = _write(tmp_path / "only.log", 2)
    assert _run(["sources", path, "--no-header"], capsys)[0] == 0
    assert _run(["sources", path, "--header"], capsys)[0] == 2
