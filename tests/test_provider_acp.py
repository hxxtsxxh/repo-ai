"""The ACP client's one permission policy, against a scripted ACP agent."""
import json
import sys
from pathlib import Path

from repo_ai.providers.acp import AcpClient, choose_permission

FAKE = Path(__file__).parent / "fake_acp_agent.py"


def _run(tmp_path, script, allowed=("app.py",), timeout=20, version=1):
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    if not (ws / "app.py").is_symlink() and not (ws / "app.py").exists():
        (ws / "app.py").write_text("x = 1\n")
    (ws / "notes.txt").write_text("line1\nline2\nline3\n")
    (tmp_path / "secret.txt").write_text("outside\n")
    log = tmp_path / "log.json"
    env = {"FAKE_ACP_SCRIPT": json.dumps(script), "FAKE_ACP_LOG": str(log), "FAKE_ACP_VERSION": str(version),
           "PATH": "/usr/bin:/bin"}
    client = AcpClient([sys.executable, str(FAKE)], ws, allowed_writes=list(allowed), env=env)
    result = client.run("Fix app.py", timeout_s=timeout)
    replies = json.loads(log.read_text()) if log.exists() else []
    return ws, result, replies


def test_reads_inside_the_workspace_and_writes_an_allowed_path(tmp_path):
    ws, result, replies = _run(tmp_path, [
        {"method": "fs/read_text_file", "params": {"path": str(tmp_path / "ws" / "notes.txt"), "line": 2, "limit": 1}},
        {"method": "fs/write_text_file", "params": {"path": str(tmp_path / "ws" / "app.py"), "content": "x = 2\n"}},
        {"say": "done"}])
    assert result.stop_reason == "end_turn" and not result.problems, result.problems
    assert replies[0]["reply"]["result"]["content"] == "line2\n"
    assert (ws / "app.py").read_text() == "x = 2\n" and result.writes == ["app.py"]
    assert "".join(result.messages) == "done" and result.agent == {"name": "fake"}


def test_reads_outside_the_workspace_and_writes_off_the_list_are_refused(tmp_path):
    ws, result, replies = _run(tmp_path, [
        {"method": "fs/read_text_file", "params": {"path": str(tmp_path / "secret.txt")}},
        {"method": "fs/read_text_file", "params": {"path": "../secret.txt"}},
        {"method": "fs/write_text_file", "params": {"path": str(tmp_path / "ws" / "notes.txt"), "content": "pwned"}},
        {"method": "fs/write_text_file", "params": {"path": str(tmp_path / "evil.py"), "content": "pwned"}}])
    assert all("error" in r["reply"] for r in replies), replies
    assert (ws / "notes.txt").read_text().startswith("line1") and not (tmp_path / "evil.py").exists()
    assert len(result.refused) == 4 and result.writes == []


def test_a_link_out_of_the_workspace_is_not_followed(tmp_path):
    (tmp_path / "ws").mkdir()
    (tmp_path / "ws" / "leak").symlink_to(tmp_path / "secret.txt")
    ws, result, replies = _run(tmp_path, [{"method": "fs/read_text_file", "params": {"path": "leak"}}])
    assert "error" in replies[0]["reply"]


def test_terminals_are_not_offered(tmp_path):
    ws, result, replies = _run(tmp_path, [{"method": "terminal/create", "params": {"command": "rm", "args": ["-rf", "/"]}}])
    assert "error" in replies[0]["reply"] and "not offered" in result.refused[0]


def test_permission_policy_allows_reads_and_edits_once_and_rejects_the_rest(tmp_path):
    opts = [{"optionId": "always", "name": "Always", "kind": "allow_always"},
            {"optionId": "once", "name": "Once", "kind": "allow_once"},
            {"optionId": "no", "name": "No", "kind": "reject_once"}]
    ws, result, replies = _run(tmp_path, [
        {"method": "session/request_permission", "params": {"toolCall": {"title": "edit", "kind": "edit"}, "options": opts}},
        {"method": "session/request_permission", "params": {"toolCall": {"title": "run", "kind": "execute"}, "options": opts}},
        {"method": "session/request_permission", "params": {"toolCall": {"title": "web", "kind": "fetch"}, "options": opts}}])
    chosen = [r["reply"]["result"]["outcome"].get("optionId") for r in replies]
    assert chosen == ["once", "no", "no"], chosen


def test_allow_always_alone_is_never_chosen():
    option, why = choose_permission({"toolCall": {"kind": "edit"},
                                     "options": [{"optionId": "a", "kind": "allow_always"}]})
    assert option is None and "never" in why


def test_another_protocol_version_is_refused(tmp_path):
    ws, result, replies = _run(tmp_path, [], version=2)
    assert any("speaks ACP 2" in p for p in result.problems) and not result.stop_reason


def test_a_run_past_its_limit_is_cancelled(tmp_path):
    ws, result, replies = _run(tmp_path, [{"sleep": 5}, {"say": "late"}], timeout=1.5)
    assert result.timed_out and not result.stop_reason


def test_a_probe_answers_from_initialize_alone(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    probe = AcpClient([sys.executable, str(FAKE)], ws, allowed_writes=[], env={"PATH": "/usr/bin:/bin"}).probe(10)
    assert probe["acp"] is True and probe["agent"] == {"name": "fake"}


def test_a_probe_of_something_that_is_not_an_acp_agent(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    probe = AcpClient([sys.executable, "-c", "import sys; sys.stdin.read()"], ws, allowed_writes=[]).probe(2)
    assert probe["acp"] is False and probe.get("problem")


def test_a_link_raced_into_the_workspace_never_leads_out(tmp_path):
    """Review of #30: the client checked a resolved path, then opened it following links; an agent swapping a file
    for a link to an outside file read and overwrote it. Every component is now opened with O_NOFOLLOW."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "sub").mkdir()
    (tmp_path / "secret.txt").write_text("outside\n")
    (ws / "app.py").symlink_to(tmp_path / "secret.txt")             # a link where the file should be
    (ws / "lnk").symlink_to(tmp_path)                                 # a link as a parent directory
    ws_, result, replies = _run(tmp_path, [
        {"method": "fs/read_text_file", "params": {"path": str(ws / "app.py")}},
        {"method": "fs/write_text_file", "params": {"path": str(ws / "app.py"), "content": "PWNED"}},
        {"method": "fs/read_text_file", "params": {"path": "lnk/secret.txt"}}], allowed=("app.py",))
    assert all("error" in r["reply"] for r in replies), replies
    assert (tmp_path / "secret.txt").read_text() == "outside\n"


def test_a_malformed_message_is_refused_not_a_crash(tmp_path):
    ws, result, replies = _run(tmp_path, [
        {"method": "session/request_permission", "params": {"toolCall": "edit", "options": [{"kind": "allow_once"}]}},
        {"method": "fs/read_text_file", "params": {"path": "a\u0000b"}}])
    assert result.stop_reason == "end_turn"
    assert all("error" in r["reply"] or r["reply"]["result"]["outcome"]["outcome"] == "cancelled" for r in replies), replies


def test_a_hard_link_to_an_outside_file_is_refused(tmp_path):
    """Review round 2 of #30: a hard link is a regular file that O_NOFOLLOW does not stop."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (tmp_path / "secret.txt").write_text("outside\n")
    import os
    os.link(tmp_path / "secret.txt", ws / "app.py")
    ws_, result, replies = _run(tmp_path, [
        {"method": "fs/read_text_file", "params": {"path": "app.py"}},
        {"method": "fs/write_text_file", "params": {"path": "app.py", "content": "PWNED"}}])
    assert all("error" in r["reply"] for r in replies), replies
    assert (tmp_path / "secret.txt").read_text() == "outside\n"


def test_a_name_that_starts_with_two_dots_is_inside():
    from pathlib import Path

    from repo_ai.providers.acp import _relative
    assert _relative(Path("/w"), "..foo") == "..foo" and _relative(Path("/w"), "../x") is None
