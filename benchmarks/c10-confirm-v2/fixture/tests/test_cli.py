import json

from logsift.cli import main


def test_summary_text(sample_log, capsys):
    assert main(["summary", str(sample_log)]) == 0
    captured = capsys.readouterr()
    assert captured.out == (
        "level     count\n"
        "ERROR         3\n"
        "INFO          2\n"
        "CRITICAL      1\n"
        "DEBUG         1\n"
        "WARNING       1\n"
    )
    assert captured.err == ""


def test_summary_json_by_component(sample_log, capsys):
    assert main(["summary", str(sample_log), "--by", "component", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out) == [
        {"component": "db", "count": 4},
        {"component": "web", "count": 3},
        {"component": "healthcheck", "count": 1},
    ]


def test_summary_of_several_files(sample_log, tmp_path, capsys):
    other = tmp_path / "other.log"
    other.write_text("2026-03-05T08:00:00Z CRITICAL db: disk full\n", encoding="utf-8")
    assert main(["summary", str(sample_log), str(other), "--by", "component"]) == 0
    assert capsys.readouterr().out.splitlines()[:2] == [
        "component    count",
        "db               5",
    ]


def test_filter_prints_matching_lines_in_order(sample_log, capsys):
    assert main(["filter", str(sample_log), "--level", "error", "--component", "web"]) == 0
    assert capsys.readouterr().out == (
        "2026-03-04T10:04:00Z ERROR web: request 991 failed\n"
        "2026-03-04T10:05:00Z CRITICAL web: worker crashed\n"
    )


def test_filter_grep(sample_log, capsys):
    assert main(["filter", str(sample_log), "--grep", "slow"]) == 0
    assert capsys.readouterr().out == "2026-03-04T10:01:00Z WARNING db: slow query took 1200 ms\n"


def test_top_text_with_limit(sample_log, capsys):
    assert main(["top", str(sample_log), "--limit", "2"]) == 0
    assert capsys.readouterr().out == (
        "message            count\n"
        "connection # lost      2\n"
        "request # failed       1\n"
    )


def test_top_json(sample_log, capsys):
    assert main(["top", str(sample_log), "--level", "CRITICAL", "--format", "json"]) == 0
    assert json.loads(capsys.readouterr().out) == [{"count": 1, "message": "worker crashed"}]


def test_export_writes_jsonl(sample_log, tmp_path, capsys):
    out = tmp_path / "errors.jsonl"
    assert main(["export", str(sample_log), "--level", "CRITICAL", "-o", str(out)]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"logsift: wrote 1 record to {out}\n"
    assert json.loads(out.read_text(encoding="utf-8")) == {
        "component": "web",
        "level": "CRITICAL",
        "lineno": 9,
        "message": "worker crashed",
        "source": str(sample_log),
        "time": "2026-03-04T10:05:00+00:00",
    }


def test_export_refuses_existing_output(sample_log, tmp_path, capsys):
    out = tmp_path / "all.jsonl"
    out.write_text("keep\n", encoding="utf-8")
    assert main(["export", str(sample_log), "-o", str(out)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"logsift: error: {out} already exists (use --force to overwrite)\n"
    assert out.read_text(encoding="utf-8") == "keep\n"


def test_export_force_replaces_output(sample_log, tmp_path, capsys):
    out = tmp_path / "all.jsonl"
    out.write_text("old\n", encoding="utf-8")
    assert main(["export", str(sample_log), "-o", str(out), "--force"]) == 0
    assert len(out.read_text(encoding="utf-8").splitlines()) == 8
    assert capsys.readouterr().err == f"logsift: wrote 8 records to {out}\n"


def test_missing_input_is_an_error(tmp_path, capsys):
    missing = tmp_path / "nope.log"
    assert main(["summary", str(missing)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"logsift: error: cannot read {missing}: No such file or directory\n"


def test_malformed_line_is_an_error(tmp_path, capsys):
    path = tmp_path / "bad.log"
    path.write_text("2026-03-04T10:00:00Z INFO web: ok\nbroken\n", encoding="utf-8")
    assert main(["filter", str(path)]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"logsift: error: cannot parse {path} line 2: 'broken'\n"


def test_config_ignore_applies_to_reports(sample_log, tmp_path, capsys):
    config = tmp_path / "logsift.toml"
    config.write_text('[logsift]\nignore = ["healthcheck"]\n', encoding="utf-8")
    assert main(["--config", str(config), "summary", str(sample_log), "--by", "component"]) == 0
    assert "healthcheck" not in capsys.readouterr().out


def test_bad_config_is_an_error(sample_log, tmp_path, capsys):
    config = tmp_path / "logsift.toml"
    config.write_text("[logsift]\nignored = []\n", encoding="utf-8")
    assert main(["--config", str(config), "summary", str(sample_log)]) == 1
    assert capsys.readouterr().err == f"logsift: error: {config}: unknown setting 'ignored'\n"


def test_missing_subcommand_is_usage_error(capsys):
    assert main([]) == 2
    assert "usage: logsift" in capsys.readouterr().err


def test_invalid_limit_is_usage_error(sample_log, capsys):
    assert main(["top", str(sample_log), "--limit", "0"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "must be a positive integer" in captured.err


def test_unknown_level_is_usage_error(sample_log, capsys):
    assert main(["filter", str(sample_log), "--level", "loud"]) == 2
    assert "unknown level 'loud'" in capsys.readouterr().err


def test_help_returns_zero(capsys):
    assert main(["--help"]) == 0
    assert "summary" in capsys.readouterr().out
