"""C13 live handoff (owner-approved 2026-11-02: a zero-cost preflight, then ONE Claude session capped at $0.50).

    python run.py preflight --work DIR --repo-ai PATH      # no model call
    python run.py live      --work DIR --repo-ai PATH      # the one approved session

PATH is the `repo-ai` of a virtualenv with the published 0.12.0 (or later) from PyPI. DIR must be under HOME. The
live step refuses to start a second session: an attempt counts as used unless its record shows no model call (the
isolation probe or a setup check refused it before any inference). Model-written code is run only by repo-ai's
sandbox and, for the hidden oracle, in a podman container without network.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
TASK = "Fix add and scale in money.py so the tests pass"
CAP = "0.50"
ORACLE_IMAGE = "localhost/c13-oracle:1"
NO_INFERENCE = {"isolation_probe_failed", "not_authenticated", "no_cost_ceiling", "help_probe_failed",
                "unsupported_version", "no_sandbox"}
MONEY = 'def add(a, b):\n    """Return a plus b."""\n    return a - b\n\n\ndef scale(x, k):\n    """Return x times k."""\n    return x + k\n'
FIX_ADD = MONEY.replace("return a - b", "return a + b")
TESTS = ("from money import add, scale\n\n\ndef test_add():\n    assert add(2, 3) == 5\n\n\n"
         "def test_scale():\n    assert scale(4, 3) == 12\n")
HIDDEN = ("from money import add, scale\n\n\ndef test_add_more():\n"
          "    assert [add(-1, 1), add(0, 0), add(2.5, 0.5), add(-4, -6)] == [0, 0, 3.0, -10]\n\n\n"
          "def test_scale_more():\n    assert [scale(3, 0), scale(-2, 3), scale(0.5, 4), scale(7, 1)] == [0, -6, 2.0, 7]\n")


def sh(argv: list[str], cwd: Path, **kw) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY",
                                                            "AI_AGENT", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
    return subprocess.run(argv, cwd=cwd, capture_output=True, text=True, env=env, **kw)


def ra(exe: str, repo: Path, *args: str, timeout: float = 1800) -> tuple[int, dict | None, str]:
    proc = sh([exe, *args], repo, timeout=timeout)
    try:
        return proc.returncode, json.loads(proc.stdout), proc.stderr[-2000:]
    except ValueError:
        return proc.returncode, None, (proc.stdout + proc.stderr)[-2000:]


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "core.hooksPath=/dev/null", "-c", "user.name=c13", "-c",
                    "user.email=c13@example.invalid", "-c", "commit.gpgsign=false", *args], cwd=repo, check=True,
                   capture_output=True)


def fixture(work: Path, exe: str) -> Path:
    repo = work / f"repo-{time.strftime('%Y%m%dT%H%M%S')}"
    (repo / "tests").mkdir(parents=True)
    (repo / "money.py").write_text(MONEY)
    (repo / "tests" / "test_money.py").write_text(TESTS)
    (repo / "pyproject.toml").write_text('[tool.pytest.ini_options]\npythonpath = ["."]\n')
    (repo / ".gitignore").write_text(".venv/\n__pycache__/\n.pytest_cache/\n")
    subprocess.run([sys.executable, "-m", "venv", str(repo / ".venv")], check=True)
    subprocess.run([str(repo / ".venv" / "bin" / "pip"), "install", "-q", "--disable-pip-version-check", "pytest"],
                   check=True)
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "two bugs")
    sh([exe, "init", "--agent", "none"], repo)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "repo-ai init", "--allow-empty")
    return repo


def log(work: Path, step: str, **data) -> None:
    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "step": step, **data}
    with (work / "records.jsonl").open("a") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")
    print(f"{step}: " + json.dumps({k: v for k, v in data.items() if k not in ("record",)})[:400])


def preflight(work: Path, exe: str, repo: Path) -> bool:
    version = sh([exe, "--version"], repo).stdout.strip()
    code, route, err = ra(exe, repo, "agents", "route", "--allow-live-provider", "--max-cost-usd", CAP, "--json")
    row = next((r for r in (route or {}).get("considered", []) if r["provider"] == "claude"), {})
    ok = bool(row.get("eligible"))
    log(work, "preflight", ok=ok, version=version, claude=row, stderr=err if not route else "")
    return ok


def oracle_image() -> bool:
    if subprocess.run(["podman", "image", "exists", ORACLE_IMAGE]).returncode == 0:
        return True
    return subprocess.run(["podman", "build", "-q", "-t", ORACLE_IMAGE, "-f", str(HERE / "Containerfile"), str(HERE)],
                          capture_output=True, timeout=1800).returncode == 0


def attempts(work: Path) -> list[dict]:
    path = work / "records.jsonl"
    rows = [json.loads(x) for x in path.read_text().splitlines()] if path.exists() else []
    return [r for r in rows if r["step"] == "live-result"]


def live(work: Path, exe: str) -> int:
    used = [a for a in attempts(work) if not a.get("no_inference")]
    if used:
        print("refusing: the approved live session was already used (see records.jsonl)")
        return 3
    if not oracle_image():
        print("refusing before any session: the oracle image could not be built")
        return 4
    repo = fixture(work, exe)
    if not preflight(work, exe, repo):
        print("refusing before any session: preflight did not find Claude eligible")
        return 2
    # 1. source: an explicitly simulated partial candidate (fixes add only), verified by repo-ai's own runs
    before = hashlib.sha256((repo / "money.py").read_bytes()).hexdigest()
    proposal = work / "proposal.json"
    proposal.write_text(json.dumps({"schema": "repo-ai.replay/1", "label": "explicit simulated proposal: fixes add only",
                                    "edits": [{"path": "money.py", "before_sha256": before, "after": FIX_ADD}]}))
    _, source, err = ra(exe, repo, "do", TASK, "--agent", "replay", "--replay", str(proposal), "--run",
                        "--allow-write", "money.py", "--max-seconds", "900", "--json")
    category = ((source or {}).get("recovery") or {}).get("category")
    log(work, "source", id=(source or {}).get("id"), verdict=(source or {}).get("effective_verdict"),
        recovery=category, stderr=err if not source else "")
    if not source or category != "partial_progress":
        print("refusing before any session: the source is not a verified partial candidate")
        return 5
    # 2. handoff to Claude, verified before use
    _, capsule, err = ra(exe, repo, "handoff", source["id"], "--to", "claude", "--json")
    capsule_path = work / f"capsule-{source['id']}.json"
    capsule_path.write_text(json.dumps(capsule or {}))
    _, check, _ = ra(exe, repo, "handoff", "--verify", str(capsule_path), "--json")
    log(work, "handoff", capsule_sha256=hashlib.sha256(capsule_path.read_bytes()).hexdigest(),
        valid=(check or {}).get("valid"), reasons=(check or {}).get("reasons"))
    if not (check or {}).get("valid"):
        print("refusing before any session: the capsule does not verify")
        return 6
    # 3. the one approved live session (Claude Code --max-budget-usd 0.50; the isolation probe runs first)
    log(work, "live-start", repo=repo.name)
    code, child, err = ra(exe, repo, "do", "--from-handoff", str(capsule_path), "--agent", "claude",
                          "--allow-live-provider", "--max-cost-usd", CAP, "--run", "--json", timeout=2400)
    prov = (child or {}).get("provider") or {}
    reasons = " ".join(str(r) for r in (child or {}).get("reasons") or []) + " ".join(
        str(r) for r in ((child or {}).get("passport") or {}).get("negative") or [])
    # a probe refusal is free only when the probe stopped before inference; "did not stop before inference" (or a
    # changed workspace) may mean a model call happened, so that attempt counts as the session
    no_inference = (prov.get("capture_status") in NO_INFERENCE and not (prov.get("events") or {}).get("assistant")
                    and "did not stop before inference" not in reasons and "changed the workspace" not in reasons)
    log(work, "live-result", exit=code, id=(child or {}).get("id"), verdict=(child or {}).get("effective_verdict"),
        provider={k: prov.get(k) for k in ("stage", "capture_status", "cost_usd", "cost_status", "auth_mode",
                                           "auth_env_vars", "verification_label")},
        continued_from=(child or {}).get("continued_from"), no_inference=no_inference, record=child,
        stderr=err if not child else "")
    if not child or not child.get("diff"):
        return 7
    # 4. hidden oracle (never in the repository or a workspace), on the candidate applied to a copy, in a container
    with tempfile.TemporaryDirectory(prefix="c13-oracle-", dir=Path.home() / ".cache") as tmp:
        copy = Path(tmp) / "c"
        subprocess.run(["git", "clone", "-q", str(repo), str(copy)], check=True, capture_output=True)
        subprocess.run(["git", "apply", "-"], cwd=copy, input=child["diff"].encode(), check=True, capture_output=True)
        (copy / "test_hidden_money.py").write_text(HIDDEN)
        res = subprocess.run(["podman", "run", "--rm", "--network=none", "--read-only", "--tmpfs", "/tmp",
                              "--cap-drop=all", "--security-opt", "no-new-privileges", "-v", f"{copy}:/work:rw", "-w",
                              "/work", "-e", "HOME=/tmp", "-e", "PYTHONDONTWRITEBYTECODE=1", ORACLE_IMAGE, "python",
                              "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_hidden_money.py", "tests"],
                             capture_output=True, text=True, timeout=600)
    log(work, "oracle", exit=res.returncode, tail=res.stdout[-800:])
    # 5. apply (post-apply verification) and undo; tracked and untracked (non-ignored) files must come back identical
    def hashes() -> str:
        files = sh(["git", "ls-files", "-co", "--exclude-standard", "-z"], repo).stdout.split("\0")
        return json.dumps({f: hashlib.sha256((repo / f).read_bytes()).hexdigest() for f in files if f
                           and (repo / f).is_file()}, sort_keys=True)
    before_apply = hashes()
    _, applied, _ = ra(exe, repo, "apply", child["id"], "--json")
    _, undone, _ = ra(exe, repo, "undo", child["id"], "--json")
    log(work, "apply-undo", applied=(applied or {}).get("applied_to_source"),
        post_apply=(applied or {}).get("post_apply_verdict"), undo_identical=hashes() == before_apply)
    _, after, _ = ra(exe, repo, "handoff", "--verify", str(capsule_path), "--json")
    log(work, "capsule-after", valid=(after or {}).get("valid"), consumed=(after or {}).get("consumed"))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["preflight", "live"])
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--repo-ai", dest="exe", required=True)
    args = ap.parse_args()
    work = args.work.resolve()
    if Path.home().resolve() not in work.parents:
        raise SystemExit("--work must be under HOME")
    work.mkdir(parents=True, exist_ok=True)
    if args.stage == "preflight":
        return 0 if preflight(work, args.exe, fixture(work, args.exe)) else 2
    return live(work, args.exe)


if __name__ == "__main__":
    sys.exit(main())
