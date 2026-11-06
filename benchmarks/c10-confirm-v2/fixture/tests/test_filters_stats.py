from logsift.filters import filter_records
from logsift.records import read_records
from logsift.stats import count_by, normalize_message, top_messages


def test_filter_by_min_level(sample_log):
    records = filter_records(read_records([str(sample_log)]), min_level="ERROR")
    assert [r.level for r in records] == ["ERROR", "ERROR", "ERROR", "CRITICAL"]


def test_filter_by_component_text_and_ignore(sample_log):
    records = read_records([str(sample_log)])
    assert {r.component for r in filter_records(records, components=["web"])} == {"web"}
    assert [r.lineno for r in filter_records(records, text="connection")] == [4, 5]
    assert "healthcheck" not in {r.component for r in filter_records(records, ignore=["healthcheck"])}


def test_count_by_orders_by_count_then_key(sample_log):
    records = read_records([str(sample_log)])
    assert count_by(records, "level") == [
        ("ERROR", 3),
        ("INFO", 2),
        ("CRITICAL", 1),
        ("DEBUG", 1),
        ("WARNING", 1),
    ]
    assert count_by(records, "component") == [("db", 4), ("web", 3), ("healthcheck", 1)]


def test_normalize_message_replaces_digit_runs():
    assert normalize_message("request 991 failed after 3 tries") == "request # failed after # tries"


def test_top_messages_limit(sample_log):
    records = read_records([str(sample_log)])
    assert top_messages(records, 2) == [("connection # lost", 2), ("ok", 1)]
