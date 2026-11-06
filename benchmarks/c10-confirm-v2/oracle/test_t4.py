"""Oracle for t4: `logsift.config.resolve_config`."""


def _config(tmp_path, names):
    path = tmp_path / "settings.toml"
    items = ", ".join(f'"{name}"' for name in names)
    path.write_text(f"[logsift]\nignore = [{items}]\n", encoding="utf-8")
    return str(path)


def _ignore(config):
    return sorted(config.ignore)


def test_t4_baseline_reads_config_file(tmp_path):
    from logsift.config import resolve_config

    config = resolve_config(_config(tmp_path, ["queue", "auth"]), {})
    assert _ignore(config) == ["auth", "queue"]


def test_t4_convention_env_list_parsing(tmp_path):
    # rule 13: LOGSIFT_IGNORE is comma-separated, items stripped, empty items dropped
    from logsift.config import resolve_config

    config = resolve_config(None, {"LOGSIFT_IGNORE": " queue ,, auth , "})
    assert _ignore(config) == ["auth", "queue"]


def test_t4_convention_env_beats_config(tmp_path):
    # rule 13: the environment variable wins over the config file (first source that provides it)
    from logsift.config import resolve_config

    config = resolve_config(_config(tmp_path, ["queue"]), {"LOGSIFT_IGNORE": "auth"})
    assert _ignore(config) == ["auth"]


def test_t4_convention_empty_env_is_unset(tmp_path):
    # rule 13: an environment variable set to the empty string counts as unset, so the config file applies
    from logsift.config import resolve_config

    config = resolve_config(_config(tmp_path, ["queue"]), {"LOGSIFT_IGNORE": ""})
    assert _ignore(config) == ["queue"]
