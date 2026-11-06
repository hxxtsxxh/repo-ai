"""Oracle for t5: top-level `--version`."""


def test_t5_baseline_shows_version(capsys):
    import logsift
    from logsift.cli import main

    main(["--version"])
    captured = capsys.readouterr()
    assert logsift.__version__ in captured.out + captured.err


def test_t5_convention_version_output(capsys):
    # rule 4: stdout is exactly "logsift <version>\n", stderr is empty, main returns 0
    import logsift
    from logsift.cli import main

    code = main(["--version"])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out == f"logsift {logsift.__version__}\n"
    assert captured.err == ""
