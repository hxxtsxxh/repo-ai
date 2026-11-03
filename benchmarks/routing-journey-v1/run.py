"""routing-journey-v1 (PREREGISTRATION.md): adaptive routing through the real CLI, with stand-in provider executables.

    python run.py --work DIR [--repo-ai "python -m repo_ai"]

No model is called and no real credential is reachable: PATH holds only the stand-ins and the system directories,
CLAUDE_CODE_OAUTH_TOKEN (when a scenario needs Claude configured) is a dummy, the Claude dedicated-login directory
is an empty one, and Codex gets a dummy dedicated login (REPO_AI_CODEX_HOME). Every scenario starts from a fresh
fixture repository. Records: DIR/records.jsonl.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DUMMY_TOKEN = "dummy-token-for-routing-journey-not-a-credential"
FIXED = "def add(a, b):\n    return a + b\n"
INIT = {"type": "system", "subtype": "init", "session_id": "s", "tools": ["Edit", "Glob", "Grep", "Read", "Write"],
        "mcp_servers": [], "skills": [], "slash_commands": [], "output_style": "default",
        "agents": ["claude", "Explore", "general-purpose", "Plan"],
        "plugins": [{"name": "cc-plugin-agents-md", "path": "builtin"}]}
PROBE_END = {"type": "result", "is_error": True, "total_cost_usd": 0, "session_id": "s"}


def claude_stub(mode: str, required_flags: list[str]) -> str:
    """A stand-in for Claude Code: help with the flags repo-ai requires, an isolation probe answered with a clean init
    event, then a run that fixes the bug (ok), hits a rejected rate limit (limited) or crashes (crash)."""
    help_text = "Usage: claude [options]\n" + "\n".join(f"  {f} <x>" for f in required_flags)
    if mode == "ok":
        run = (f"printf '%s' {shlex.quote(FIXED)} > \"$REPO_AI_WORKSPACE/m.py\"\n"
               f"echo '{json.dumps(INIT)}'\n"
               "echo '{\"type\":\"result\",\"is_error\":false,\"result\":\"fixed\",\"session_id\":\"s\","
               "\"total_cost_usd\":0.01}'\n")
    elif mode == "limited":
        run = (f"echo '{json.dumps(INIT)}'\n"
               "echo '{\"type\":\"rate_limit_event\",\"rate_limit_info\":{\"status\":\"rejected\","
               "\"rateLimitType\":\"five_hour\"},\"session_id\":\"s\"}'\n"
               "echo '{\"type\":\"result\",\"is_error\":true,\"result\":\"usage limit reached\",\"session_id\":\"s\","
               "\"total_cost_usd\":0}'\nexit 1\n")
    elif mode == "notloggedin":  # what Claude Code prints without a login
        run = (f"echo '{json.dumps(INIT)}'\n"
               "echo '{\"type\":\"result\",\"is_error\":true,\"result\":\"Not logged in \u00b7 Please run /login\","
               "\"session_id\":\"s\",\"total_cost_usd\":0}'\nexit 1\n")
    else:
        run = "echo 'Segmentation fault (stand-in crash)' >&2\nexit 139\n"
    return (f"#!/bin/sh\nif [ \"$1\" = \"--help\" ]; then cat <<'EOF'\n{help_text}\nEOF\nexit 0; fi\n"
            "if [ \"$1\" = \"--version\" ]; then echo '2.1.316 (Claude Code)'; exit 0; fi\n"
            "for a in \"$@\"; do if [ \"$a\" = \"repo-ai-isolation-probe-not-a-model\" ]; then\n"
            f"  echo '{json.dumps(INIT)}'; echo '{json.dumps(PROBE_END)}'; exit 1; fi; done\n" + run)


CODEX_STUB = f"""#!/bin/sh
if [ "$1" = "--version" ]; then echo "codex-cli 0.165.0"; exit 0; fi
case "$*" in *--help*) echo 'Usage: codex exec [OPTIONS]'; echo '  --json'; exit 0;; esac
printf '%s' {shlex.quote(FIXED)} > "$REPO_AI_WORKSPACE/m.py"
echo '{{"type":"thread.started","thread_id":"t1"}}'
echo '{{"type":"turn.started","thread_id":"t1"}}'
echo '{{"type":"item.completed","thread_id":"t1","item":{{"id":"i1","type":"file_change","changes":[{{"path":"m.py","kind":"update"}}],"status":"completed"}}}}'
echo '{{"type":"turn.completed","thread_id":"t1","usage":{{"input_tokens":10,"output_tokens":5}}}}'
"""


class Journey:
    def __init__(self, work: Path, repo_ai: list[str], python: str) -> None:
        self.work, self.repo_ai, self.python = work, repo_ai, python
        self.log_path = work / "records.jsonl"
        from repo_ai.providers import claude_auth
        self.flags = list(claude_auth.REQUIRED_FLAGS)

    def log(self, scenario: str, step: str, **data) -> dict:
        row = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "scenario": scenario, "step": step, **data}
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
        print(f"[{scenario}] {step}: " + json.dumps({k: v for k, v in data.items() if k != "raw"})[:240])
        return row

    def fixture(self, name: str, stubs: dict[str, str], *, token: bool,
                login_dir: bool = True) -> tuple[Path, dict[str, str]]:
        base = self.work / name
        shutil.rmtree(base, ignore_errors=True)
        (base / "bin").mkdir(parents=True)
        for exe, body in stubs.items():
            (base / "bin" / exe).write_text(body)
            (base / "bin" / exe).chmod(0o755)
        if login_dir:
            (base / "claude-login").mkdir()  # exists but empty: configured, never logged in
        (base / "codex-login").mkdir()
        (base / "codex-login" / "auth.json").write_text(json.dumps({"OPENAI_API_KEY": "dummy-not-a-credential"}))
        repo = base / "repo"
        (repo / "tests").mkdir(parents=True)
        (repo / "m.py").write_text("def add(a, b):\n    return a - b\n")
        (repo / "tests" / "test_m.py").write_text("from m import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n")
        (repo / "pyproject.toml").write_text('[tool.pytest.ini_options]\npythonpath = ["."]\n')
        (repo / ".gitignore").write_text(".venv/\n__pycache__/\n.pytest_cache/\n.repo-ai/\n")
        subprocess.run([self.python, "-m", "venv", str(repo / ".venv")], check=True)
        subprocess.run([str(repo / ".venv" / "bin" / "pip"), "install", "-q", "--disable-pip-version-check", "pytest"],
                       check=True)
        git = ["git", "-c", "core.hooksPath=/dev/null", "-c", "user.name=r", "-c", "user.email=r@example.invalid"]
        subprocess.run([*git, "init", "-q"], cwd=repo, check=True)
        subprocess.run([*git, "add", "-A"], cwd=repo, check=True)
        subprocess.run([*git, "commit", "-qm", "bug"], cwd=repo, check=True)
        env = {k: v for k, v in os.environ.items()
               if k not in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AI_AGENT", "CLAUDECODE",
                            "CLAUDE_CODE_ENTRYPOINT", "REPO_AI_CODEX_BROKER")}
        env.update(PATH=f"{base / 'bin'}:/usr/bin:/bin", REPO_AI_CLAUDE_CONFIG_DIR=str(base / "claude-login"),
                   REPO_AI_CODEX_HOME=str(base / "codex-login"))
        if token:
            env["CLAUDE_CODE_OAUTH_TOKEN"] = DUMMY_TOKEN
        return repo, env

    def cli(self, repo: Path, env: dict[str, str], *args: str) -> tuple[int, dict | None, str]:
        proc = subprocess.run([*self.repo_ai, *args], cwd=repo, env=env, capture_output=True, text=True, timeout=600)
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            data = None
        return proc.returncode, data, (proc.stderr or "")[-600:]

    def route(self, sc: str, repo: Path, env: dict[str, str], *extra: str, step: str = "route") -> dict:
        _, data, err = self.cli(repo, env, "agents", "route", "--allow-live-provider", "--json", *extra)
        data = data or {}
        rows = {r["provider"]: {k: r.get(k) for k in ("readiness", "eligible", "cooling_down", "observation_stale",
                                                       "auth_observed", "cost_semantics", "reasons")}
                for r in data.get("considered", []) if r.get("installed") or r["provider"] in ("claude", "codex")}
        return self.log(sc, step, outcome=data.get("outcome"), selected=data.get("selected"), providers=rows,
                        args=list(extra), stderr=err if not data else "")

    def mission(self, sc: str, repo: Path, env: dict[str, str], agent: str = "auto", *extra: str,
                step: str = "mission") -> dict:
        # the scenario and step in the task: the same task on the same commit returns the stored mission, unrun
        code, data, err = self.cli(repo, env, "do", f"Fix add in m.py so the test passes ({sc} {step})", "--agent", agent,
                                   "--allow-live-provider", "--run", "--allow-write", "m.py", "--json", *extra)
        data = data or {}
        prov = data.get("provider") or {}
        return self.log(sc, step, exit=code, mission_id=data.get("id"),
                        ceiling=(data.get("contract") or {}).get("max_cost_usd"),
                        verdict=data.get("effective_verdict", data.get("verdict")),
                        decision=data.get("decision"), contract_provider=(data.get("contract") or {}).get("provider"),
                        provider={k: prov.get(k) for k in ("name", "stage", "rate_limited", "cost_usd", "cost_status",
                                                           "capture_status", "verification_label", "auth_mode")},
                        recovery=(data.get("recovery") or {}).get("category"), reasons=data.get("reasons"),
                        stderr=err if not data else "")

    def policy(self, repo: Path) -> tuple[Path, dict]:
        path = repo / ".repo-ai" / "state" / "providers.json"
        return path, json.loads(path.read_text()) if path.exists() else {}

    # -- scenarios ------------------------------------------------------------------------------------------------
    def run_all(self) -> None:
        stub = lambda mode: claude_stub(mode, self.flags)  # noqa: E731

        repo, env = self.fixture("Z1-zero", {}, token=False)
        self.route("Z1-zero", repo, env)
        self.mission("Z1-zero", repo, env)

        repo, env = self.fixture("U1-unauthenticated", {"claude": stub("ok")}, token=False, login_dir=False)
        self.route("U1-unauthenticated", repo, env)
        self.mission("U1-unauthenticated", repo, env, "auto", "--max-cost-usd", "0.5")

        repo, env = self.fixture("U2-configured-not-logged-in", {"claude": stub("notloggedin")}, token=False)
        self.route("U2-configured-not-logged-in", repo, env)
        self.mission("U2-configured-not-logged-in", repo, env, "auto", "--max-cost-usd", "0.5")
        self.route("U2-configured-not-logged-in", repo, env, step="route-after-not-logged-in")

        repo, env = self.fixture("O1-one", {"claude": stub("ok")}, token=True)
        self.route("O1-one", repo, env)
        self.mission("O1-one", repo, env, "auto", "--max-cost-usd", "0.5")
        self.route("O1-one", repo, env, step="route-after-success")
        # E1 (expired readiness), on the same repository: the READY observation expires, then the binary changes
        path, pol = self.policy(repo)
        self.log("E1-expired", "observation-before", observations=pol.get("observations"))
        for obs in pol.get("observations", {}).values():
            obs["until"] = time.time() - 1  # controlled injection: the observation's TTL has passed
        path.write_text(json.dumps(pol))
        self.route("E1-expired", repo, env, step="route-after-expiry")
        self.mission("E1-expired", repo, env, "auto", "--max-cost-usd", "0.5", step="mission-after-expiry")
        self.route("E1-expired", repo, env, step="route-after-second-success")
        exe = repo.parent / "bin" / "claude"
        exe.write_text(exe.read_text() + "# another build\n")
        self.route("E1-expired", repo, env, step="route-after-binary-change")

        repo, env = self.fixture("M1-many", {"claude": stub("ok"), "codex": CODEX_STUB}, token=True)
        self.route("M1-many", repo, env)
        self.route("M1-many", repo, env, "--max-cost-usd", "0.5", step="route-with-usd-ceiling")
        code, _, err = self.cli(repo, env, "agents", "authorize", "codex", "--prefer")
        self.log("M1-many", "authorize-codex-prefer", exit=code, stderr=err)
        self.route("M1-many", repo, env, step="route-with-preference")

        repo, env = self.fixture("Q1-quota", {"claude": stub("limited"), "codex": CODEX_STUB}, token=True)
        self.route("Q1-quota", repo, env)
        self.mission("Q1-quota", repo, env, "auto", "--max-cost-usd", "0.5")
        self.route("Q1-quota", repo, env, step="route-after-rate-limit")
        # Q2: under a USD ceiling, the uncapped provider is no fallback
        self.route("Q2-ceiling-blocks-fallback", repo, env, "--max-cost-usd", "0.5", step="route-with-usd-ceiling")
        self.mission("Q2-ceiling-blocks-fallback", repo, env, "auto", "--max-cost-usd", "0.5")
        self.mission("F1-fallback", repo, env)  # the next run without a ceiling: codex is selected
        self.mission("A1-explicit-while-cooling", repo, env, "claude", "--max-cost-usd", "0.5")
        path, pol = self.policy(repo)
        self.log("C1-cooldown-expiry", "policy-before", cooldown=pol.get("cooldown"), observations=pol.get("observations"))
        for name in list(pol.get("cooldown", {})):
            pol["cooldown"][name] = time.time() - 1  # controlled injection: the cooldown has passed
        for obs in pol.get("observations", {}).values():
            if obs.get("state") == "USAGE_LIMITED":
                obs["until"] = time.time() - 1
        path.write_text(json.dumps(pol))
        self.route("C1-cooldown-expiry", repo, env, step="route-after-cooldown")

        repo, env = self.fixture("X1-failure", {"claude": stub("crash"), "codex": CODEX_STUB}, token=True)
        self.mission("X1-failure", repo, env, "auto", "--max-cost-usd", "0.5")
        self.route("X1-failure", repo, env, step="route-after-failure")

        # P1 (unsupported platform): in-process, the platform name patched; discovery and routing are real
        repo, env = self.fixture("P1-unsupported-platform", {"claude": stub("ok"), "codex": CODEX_STUB}, token=True)
        code = ("import json, sys\nfrom pathlib import Path\nfrom repo_ai.providers import adapters, registry\n"
                "class Win:  # only the adapters module sees another platform name\n"
                "    platform = 'win32'\n"
                "    def __getattr__(self, name):\n        return getattr(sys, name)\n"
                "adapters.sys = Win()\n"
                "r = registry.route(Path('.'), run_authorized=True)\n"
                "print(json.dumps({'outcome': r['outcome'], 'selected': r['selected'], 'rows': {c['provider']: "
                "[c['readiness'], c['reasons']] for c in r['considered'] if c['installed']}}))\n")
        proc = subprocess.run([self.repo_ai[0], "-c", code], cwd=repo, env=env, capture_output=True, text=True,
                              timeout=120)
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            data = {"stderr": proc.stderr[-600:]}
        self.log("P1-unsupported-platform", "route-as-win32", **data)


# (scenario, step) -> what must hold; checked against the records after the run (PREREGISTRATION.md)
def _route(outcome, selected=None, **readiness):
    return lambda r: r.get("outcome") == outcome and r.get("selected") == selected and all(
        (r.get("providers") or {}).get(p, {}).get("readiness") == want for p, want in readiness.items())


def _mission(verdict=None, provider=None, refused=False, rate_limited=None, cost_status=None, not_recovery=None,
             recovery=None, says=None):
    def check(r):
        if refused:  # refused with the stated reason, before any provider started (never a traceback)
            return (r["exit"] == 1 and r.get("verdict") is None and not (r.get("provider") or {}).get("name")
                    and says in (r.get("stderr") or "") and "Traceback" not in (r.get("stderr") or ""))
        p = r.get("provider") or {}
        return (r.get("verdict") == verdict and r.get("contract_provider") == provider and p.get("name") == provider
                and (rate_limited is None or p.get("rate_limited") is rate_limited)
                and (cost_status is None or p.get("cost_status") == cost_status)
                and (recovery is None or r.get("recovery") == recovery)
                and (not_recovery is None or r.get("recovery") != not_recovery))
    return check


EXPECT = {
    ("Z1-zero", "route"): _route("NO_AGENT", claude="NOT_INSTALLED", codex="NOT_INSTALLED"),
    ("Z1-zero", "mission"): _mission(refused=True, says='no provider can run this mission (NO_AGENT)'),
    ("U1-unauthenticated", "route"): _route("NO_AGENT", claude="SETUP_REQUIRED"),
    ("U1-unauthenticated", "mission"): _mission(refused=True, says='no provider can run this mission (NO_AGENT)'),
    ("U2-configured-not-logged-in", "route"): _route("SELECTED", "claude", claude="INSTALLED_UNPROBED"),
    ("U2-configured-not-logged-in", "mission"): _mission("BLOCKED", "claude", recovery="provider_unavailable"),
    ("U2-configured-not-logged-in", "route-after-not-logged-in"): _route("NO_AGENT", claude="AUTHORIZED_BUT_UNREADY"),
    ("O1-one", "route"): _route("SELECTED", "claude", claude="INSTALLED_UNPROBED"),
    ("O1-one", "mission"): _mission("PASS", "claude", cost_status="OBSERVED"),
    ("O1-one", "route-after-success"): _route("SELECTED", "claude", claude="READY"),
    ("E1-expired", "route-after-expiry"): _route("SELECTED", "claude", claude="INSTALLED_UNPROBED"),
    ("E1-expired", "mission-after-expiry"): _mission("PASS", "claude"),
    ("E1-expired", "route-after-second-success"): _route("SELECTED", "claude", claude="READY"),
    ("E1-expired", "route-after-binary-change"): _route("SELECTED", "claude", claude="INSTALLED_UNPROBED"),
    ("M1-many", "route"): _route("SELECTED", "claude", claude="INSTALLED_UNPROBED", codex="INSTALLED_UNPROBED"),
    ("M1-many", "route-with-usd-ceiling"): lambda r: _route("SELECTED", "claude")(r) and
        r["providers"]["codex"]["eligible"] is False and r["providers"]["codex"]["cost_semantics"].startswith("UNKNOWN"),
    ("M1-many", "route-with-preference"): _route("SELECTED", "codex"),
    ("Q1-quota", "mission"): _mission("BLOCKED", "claude", rate_limited=True, recovery="provider_unavailable"),
    ("Q1-quota", "route-after-rate-limit"): _route("SELECTED", "codex", claude="USAGE_LIMITED"),
    ("Q2-ceiling-blocks-fallback", "route-with-usd-ceiling"): _route("NO_AGENT", claude="USAGE_LIMITED"),
    ("Q2-ceiling-blocks-fallback", "mission"): _mission(refused=True, says='no provider can run this mission (NO_AGENT)'),
    ("F1-fallback", "mission"): _mission("PASS", "codex", cost_status="UNKNOWN"),
    ("A1-explicit-while-cooling", "mission"): _mission(refused=True, says='is cooling down until'),
    ("C1-cooldown-expiry", "route-after-cooldown"): _route("SELECTED", "claude", claude="INSTALLED_UNPROBED"),
    ("X1-failure", "mission"): _mission("BLOCKED", "claude", rate_limited=False, recovery="contract_failure"),
    ("X1-failure", "route-after-failure"): lambda r: _route("SELECTED", "claude")(r) and
        not r["providers"]["claude"]["cooling_down"],
    ("P1-unsupported-platform", "route-as-win32"): lambda r: r.get("outcome") == "NO_AGENT" and all(
        v[0] == "ISOLATION_BLOCKED" for v in (r.get("rows") or {"": ["missing"]}).values()),
}


def evaluate(work: Path) -> dict:
    rows = [json.loads(line) for line in (work / "records.jsonl").read_text().splitlines()]
    seen = {(r["scenario"], r["step"]): r for r in rows}
    results = {f"{sc} {st}": (bool(check(seen[(sc, st)])) if (sc, st) in seen else None)
               for (sc, st), check in EXPECT.items()}
    # G2: no mission ran a provider other than the one its contract names (no silent fallback inside a run)
    g2 = [f"{r['scenario']} {r['step']}" for r in rows if "mission" in r["step"] and (r.get("provider") or {}).get("name")
          and r["provider"]["name"] != r.get("contract_provider")]
    # G3: no run of a provider without an enforceable ceiling reports an observed cost
    g3 = [f"{r['scenario']} {r['step']}" for r in rows if "mission" in r["step"]
          and (r.get("provider") or {}).get("name") == "codex" and r["provider"].get("cost_status") == "OBSERVED"]
    # G4 (amendment 2): a ceiling-enforcing provider (claude) was started without a usable ceiling
    started_claude = [r for r in rows if "mission" in r["step"] and (r.get("provider") or {}).get("name") == "claude"
                      and (r.get("provider") or {}).get("capture_status") != "no_cost_ceiling"]
    g4 = [f"{r['scenario']} {r['step']}" for r in started_claude if "ceiling" in r and float(r["ceiling"] or 0) < 0.0001]
    g4_unrecorded = [f"{r['scenario']} {r['step']}" for r in started_claude if "ceiling" not in r]
    summary = {"G1_expected": sum(1 for v in results.values() if v), "G1_total": len(results),
               "G1_failed": sorted(k for k, v in results.items() if v is not True), "G2_violations": g2,
               "G3_violations": g3, "G4_uncapped_starts": g4, "G4_ceiling_not_recorded": g4_unrecorded}
    (work / "evaluation.json").write_text(json.dumps({"summary": summary, "checks": results}, indent=1, sort_keys=True))
    print(json.dumps(summary, indent=1))
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--python", default=sys.executable, help="interpreter with pytest for the fixture venvs")
    args = ap.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    Journey(args.work.resolve(), [sys.executable, "-m", "repo_ai"], args.python).run_all()
    summary = evaluate(args.work.resolve())
    return 0 if summary["G1_expected"] == summary["G1_total"] and not summary["G2_violations"] \
        and not summary["G3_violations"] and not summary["G4_uncapped_starts"] else 1


if __name__ == "__main__":
    sys.exit(main())
