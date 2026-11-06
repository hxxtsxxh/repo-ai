import pytest

from logsift.config import Config, load_config
from logsift.errors import ConfigError, OutputExistsError
from logsift.output import write_text
from logsift.render import render_json, render_table, rows_to_objects


def test_render_table_aligns_columns():
    text = render_table(["level", "count"], [("ERROR", 12), ("INFO", 3)])
    assert text == "level  count\nERROR     12\nINFO       3\n"


def test_render_table_without_rows():
    assert render_table(["level", "count"], []) == "level  count\n"


def test_render_json_is_sorted_and_indented():
    value = rows_to_objects(["level", "count"], [("ERROR", 2)])
    assert render_json(value) == '[\n  {\n    "count": 2,\n    "level": "ERROR"\n  }\n]\n'


def test_write_text_uses_utf8_and_lf(tmp_path):
    path = tmp_path / "out.txt"
    write_text(str(path), "café\r\nline two")
    assert path.read_bytes() == "café\r\nline two\n".encode("utf-8")
    write_text(str(path), "a\nb\n", force=True)
    assert path.read_bytes() == b"a\nb\n"


def test_write_text_refuses_existing_file(tmp_path):
    path = tmp_path / "out.txt"
    path.write_text("old", encoding="utf-8")
    with pytest.raises(OutputExistsError) as info:
        write_text(str(path), "new\n")
    assert str(info.value) == f"{path} already exists (use --force to overwrite)"
    assert path.read_text(encoding="utf-8") == "old"


def test_load_config_reads_ignore(tmp_path):
    path = tmp_path / "logsift.toml"
    path.write_text('[logsift]\nignore = ["healthcheck", "metrics"]\n', encoding="utf-8")
    assert load_config(str(path)) == Config(ignore=("healthcheck", "metrics"))


def test_load_config_without_table(tmp_path):
    path = tmp_path / "logsift.toml"
    path.write_text("", encoding="utf-8")
    assert load_config(str(path)) == Config()


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("[logsift]\ncolour = true\n", "unknown setting 'colour'"),
        ('[logsift]\nignore = "web"\n', "'ignore' must be a list of strings"),
        ("[logsift\n", "invalid TOML"),
    ],
)
def test_load_config_errors(tmp_path, content, message):
    path = tmp_path / "logsift.toml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ConfigError, match=message):
        load_config(str(path))
