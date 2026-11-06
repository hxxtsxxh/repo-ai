"""Oracle for t8: `logsift.config.read_name_list`."""


def test_t8_baseline_reads_names(tmp_path):
    from logsift.config import read_name_list

    path = tmp_path / "names.txt"
    path.write_text("# noisy components\nprobe\n\n  kube-proxy  \n# end\nsidecar\n", encoding="utf-8")
    assert list(read_name_list(str(path))) == ["probe", "kube-proxy", "sidecar"]


def test_t8_convention_missing_file_error(tmp_path):
    # rule 1: an OSError is re-raised as LogsiftError with the message "cannot read <path>: <strerror>"
    from logsift.config import read_name_list
    from logsift.errors import LogsiftError

    missing = str(tmp_path / "absent-names.txt")
    try:
        read_name_list(missing)
    except LogsiftError as exc:
        assert str(exc) == f"cannot read {missing}: No such file or directory"
    else:
        raise AssertionError("read_name_list did not raise LogsiftError")
