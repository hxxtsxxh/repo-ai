"""Release review D2: user-named reports must not disappear silently or be deleted."""
from conftest import run_cli


def test_uninstall_discloses_retained_reports_in_preview_and_execution(pyweb):
    assert run_cli(pyweb, "init", "--agent", "claude", "-q").returncode == 0
    report = pyweb / ".repo-ai" / "proof.md"
    report.write_text("An exported report, possibly edited by its owner.\n")
    nested = pyweb / ".repo-ai" / "reports" / "custom.json"
    nested.parent.mkdir()
    nested.write_text('{"user": "data"}\n')
    for args in [("--dry-run",), ("-y",)]:
        result = run_cli(pyweb, "uninstall", *args)
        assert result.returncode == 0, result.stderr
        assert ".repo-ai/proof.md" in result.stdout and "kept" in result.stdout
        assert ".repo-ai/reports/custom.json" in result.stdout
        assert report.read_text() == "An exported report, possibly edited by its owner.\n"
        assert nested.read_text() == '{"user": "data"}\n'


def test_uninstall_preserves_and_discloses_unreadable_user_directory(pyweb, monkeypatch):
    from pathlib import Path
    from repo_ai.config import load_config
    from repo_ai.paths import resolve_layout
    from repo_ai.workspace import plan_uninstall

    assert run_cli(pyweb, "init", "--agent", "none", "-q").returncode == 0
    private = pyweb / ".repo-ai" / "private-reports"
    private.mkdir()
    (private / "report.md").write_text("keep me")
    original = Path.iterdir

    def unreadable(path):
        if path == private:
            raise PermissionError("directory cannot be read")
        return original(path)

    monkeypatch.setattr(Path, "iterdir", unreadable)
    cfg = load_config(pyweb)
    layout = resolve_layout(pyweb, cfg, prefer="standard")
    plan, _ = plan_uninstall(pyweb, cfg, layout, (), ())
    assert (private, "unreadable user directory; kept") in plan.skipped
    assert (private / "report.md").read_text() == "keep me"
