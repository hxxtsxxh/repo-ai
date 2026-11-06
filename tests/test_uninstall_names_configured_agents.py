"""`uninstall --dry-run` names the agents init configured, not its cleanup list (found re-capturing the quickstart)."""
from conftest import run_cli


def test_a_no_agent_install_is_not_described_as_removing_bob_and_claude(pyweb):
    assert run_cli(pyweb, "init", "--agent", "none", "-q").returncode == 0
    out = run_cli(pyweb, "uninstall", "--dry-run").stdout
    assert "removing: no agent integration was configured (and any leftover files of other agents)" in out
    assert "removing: bob, claude" not in out


def test_a_configured_agent_is_named(pyweb):
    assert run_cli(pyweb, "init", "--agent", "claude", "-q").returncode == 0
    out = run_cli(pyweb, "uninstall", "--dry-run").stdout
    assert "removing: claude (and any leftover files of other agents)" in out


def test_an_explicit_agent_is_named_as_given(pyweb):
    assert run_cli(pyweb, "init", "--agent", "claude", "-q").returncode == 0
    out = run_cli(pyweb, "uninstall", "--agent", "claude", "--dry-run").stdout
    assert "removing: claude;" in out
