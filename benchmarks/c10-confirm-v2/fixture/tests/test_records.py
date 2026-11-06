from datetime import datetime, timezone

import pytest

from logsift.errors import LogsiftError, ParseError
from logsift.records import level_rank, parse_line, read_records


def test_parse_line_fields():
    record = parse_line("2026-03-04T10:15:00Z ERROR db: connection lost", "a.log", 7)
    assert record.time == datetime(2026, 3, 4, 10, 15, tzinfo=timezone.utc)
    assert record.level == "ERROR"
    assert record.component == "db"
    assert record.message == "connection lost"
    assert (record.source, record.lineno) == ("a.log", 7)


def test_parse_line_converts_offset_to_utc():
    record = parse_line("2026-03-04T12:15:00+02:00 INFO web: up")
    assert record.time == datetime(2026, 3, 4, 10, 15, tzinfo=timezone.utc)
    assert record.time.utcoffset().total_seconds() == 0


@pytest.mark.parametrize(
    "line",
    [
        "not a log line",
        "2026-03-04T10:15:00Z NOTICE db: unknown level",
        "2026-03-04T10:15:00 INFO db: no time zone",
        "yesterday INFO db: bad time",
    ],
)
def test_parse_line_rejects_malformed(line):
    with pytest.raises(ParseError):
        parse_line(line)


def test_parse_error_message():
    with pytest.raises(ParseError) as info:
        parse_line("garbage", "x.log", 3)
    assert str(info.value) == "cannot parse x.log line 3: 'garbage'"


def test_level_rank_orders_by_severity():
    assert level_rank("DEBUG") < level_rank("INFO") < level_rank("WARNING")
    assert level_rank("WARNING") < level_rank("ERROR") < level_rank("CRITICAL")


def test_read_records_ignores_blank_lines_and_keeps_line_numbers(sample_log):
    records = read_records([str(sample_log)])
    assert len(records) == 8
    assert records[5].component == "healthcheck"
    assert records[5].lineno == 7


def test_read_records_missing_file(tmp_path):
    missing = tmp_path / "missing.log"
    with pytest.raises(LogsiftError, match="^cannot read .*missing.log: No such file or directory$"):
        read_records([str(missing)])


def test_read_records_rejects_invalid_utf8(tmp_path):
    path = tmp_path / "bad.log"
    path.write_bytes(b"2026-03-04T10:15:00Z INFO db: \xff\n")
    with pytest.raises(LogsiftError, match="not valid UTF-8"):
        read_records([str(path)])
