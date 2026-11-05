#!/usr/bin/env python3
"""Held-out-6 constructed scenarios (PROTOCOL.md Amendment 5): can
`repo-ai verify --run`, `repo-ai evidence` or the completion gate present a
failing (or hanging) change as passing, current or verified?

    VEV_WORK=... python scenarios.py <project> [...]   ->  $VEV_WORK/scenarios-<project>.json

Every scenario is built mechanically from the project's ground truth
(`harness.py`: `setup.json`, `baseline.json`, `changes.json`, `truth.json`):
the same rules pick the same files and changes on every project. Its label
(does the state contain a new failure or a hang?) is fixed by construction
and then *validated* by running the affected test files alone in the
project's network-less container (the harness driver), before and
independently of any verify outcome. A scenario whose construction does not
validate is recorded as invalid and excluded from scoring; nothing is
rebuilt after a verify outcome is seen.

This file only records. `score6.py` applies the frozen rules.
"""

from __future__ import annotations

import json
import shlex
import os
import re
import shutil
import statistics
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import harness as H  # noqa: E402
import wallclock as W  # noqa: E402

PASSING = W.PASSING
HANG_CHECK_S = 30.0       # a construction "hangs" if the file alone has not finished after this
H3_TIMEOUT = "60"         # H3 only: the base itself hangs, so --record and --run get an explicit limit
FLAKY_RUNS = 3

# ---------------------------------------------------------------------------
# injected tests (self-contained; appended to an existing test file, or a new file)
# ---------------------------------------------------------------------------
PY = {
    "fail": "    def test_zz_injected_{tag}(self):\n        self.assertEqual('zz injected {tag}', 'failure')\n",
    "hang": "    def test_zz_injected_{tag}(self):\n        import time\n        time.sleep(100000)\n",
    "flaky": "    def test_zz_injected_{tag}(self):\n        import os\n"
             "        self.assertLess(os.urandom(1)[0], 128, 'zz injected {tag}')\n",
}
JS = {
    "fail": "__zz_{tag}('zz injected {tag}', () => {{ throw new Error('zz injected {tag}'); }});\n",
    "hang": "__zz_{tag}('zz injected {tag}', async () => {{ await new Promise((r) => setTimeout(r, 1e8)); }});\n",
    "flaky": "__zz_{tag}('zz injected {tag}', () => {{ if (Math.random() < 0.5) throw new Error('zz injected {tag}'); }});\n",
}


def _esm(repo: Path, rel: str, text: str) -> bool:
    if rel.endswith((".mjs", ".mts")):
        return True
    if rel.endswith((".cjs", ".cts")):
        return False
    if re.search(r"^\s*(import|export)\s", text, re.M):
        return True
    if re.search(r"\brequire\s*\(", text):
        return False
    d = (repo / rel).parent
    while True:
        pj = d / "package.json"
        if pj.is_file():
            try:
                return json.loads(pj.read_text("utf-8")).get("type") == "module"
            except ValueError:
                return False
        if d == repo or d == d.parent:
            return False
        d = d.parent


def snippet(repo: Path, rel: str, what: str, tag: str, text: str = "") -> str:
    if rel.endswith(".py"):
        return (f"\n\nimport unittest as _zz_unittest_{tag}\n\n\n"
                f"class ZzInjected_{tag}(_zz_unittest_{tag}.TestCase):\n" + PY[what].format(tag=tag))
    head = (f"import {{ test as __zz_{tag} }} from 'node:test';\n" if _esm(repo, rel, text)
            else f"const __zz_{tag} = require('node:test');\n")
    return "\n" + head + JS[what].format(tag=tag)


def inject(repo: Path, rel: str, what: str, tag: str) -> None:
    path = repo / rel
    text = path.read_text("utf-8")
    path.write_text(text.rstrip("\n") + "\n" + snippet(repo, rel, what, tag, text), "utf-8")


def new_test_name(rel: str) -> str:
    """A new file next to `rel` that the same discovery rules collect."""
    d, base = os.path.split(rel)
    if base.startswith("test_"):
        name = "test_zzinj_" + base[5:]
    elif base.startswith("test-"):
        name = "test-zzinj-" + base[5:]
    elif base.startswith("test") and base.endswith(".py"):
        name = "test_zzinj" + base[4:]
    else:
        name = "zzinj_" + base
    return os.path.join(d, name) if d else name


# ---------------------------------------------------------------------------
# picks (fixed rules; PROTOCOL.md Amendment 5)
# ---------------------------------------------------------------------------
def picks(name: str) -> dict:
    base = H.load(name, "baseline")
    changes = H.load(name, "changes")
    truth = H.load(name, "truth")
    ok = sorted(t for t, r in base.items() if r.get("exit") == 0 and r.get("ran") != 0)
    durs = [base[t]["dur"] for t in ok]
    med = statistics.median(durs) if durs else 0.0
    short = [t for t in ok if base[t]["dur"] <= med]
    failing = [c for c in changes if (truth.get(c["id"]) or {}).get("affected")
               and not (truth.get(c["id"]) or {}).get("timeouts")
               and set(truth[c["id"]]["affected"]) <= set(ok)]
    passing = [c for c in changes if not (truth.get(c["id"]) or {}).get("affected")
               and not (truth.get(c["id"]) or {}).get("timeouts")]
    m = failing[0] if failing else None
    src = [p for p, v in (m or {}).get("files", {}).items() if v is not None]
    return {
        "T": short[0] if short else None, "T2": short[1] if len(short) > 1 else None,
        "Hf": ok[0] if len(ok) > 1 else None, "Ff": ok[-1] if len(ok) > 1 else None,
        "M": m["id"] if m else None, "M2": failing[1]["id"] if len(failing) > 1 else None,
        "P": passing[0]["id"] if passing else None,
        "M_file": src[0] if len(src) == 1 else None,
        "M_affected": truth[m["id"]]["affected"] if m else [],
        "base_passing": ok,
    }


def change(name: str, cid: str) -> dict:
    return next(c for c in H.load(name, "changes") if c["id"] == cid)


# ---------------------------------------------------------------------------
# clones, commands
# ---------------------------------------------------------------------------
def tc_for(name: str, image: bool = True) -> list[str]:
    proj = H.CORPUS[name]
    if proj.get("image") or name in W.PODMAN:
        sb = ["--sandbox", "podman"] + (["--image", proj["image"]] if proj.get("image") and image else [])
    else:
        sb = []
    return ["--test-command", proj["test_command"], *sb]


def git_c(repo: Path, *args: str) -> None:
    H.git(repo, "-c", "user.email=e@e", "-c", "user.name=e", *args)


def fresh(name: str, label: str, base_edit=None, record_args: tuple[str, ...] = ()) -> tuple[Path, dict]:
    src = H.WORK / "repos" / name
    repo = H.WORK / "scen" / name / label
    if repo.exists():
        shutil.rmtree(repo)
    repo.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "-q", "--local", "--no-hardlinks", str(src), str(repo)], check=True)
    H.git(repo, "checkout", "-q", "--detach", H.git(src, "rev-parse", "HEAD").strip())
    H._install_metadata(repo)
    if base_edit is not None:
        base_edit(repo)
        H.git(repo, "add", "-A")
        git_c(repo, "commit", "-qm", "zz: scenario base")
    init = W.ra("new", repo, "init", "--agent", "none", "-q")
    H.git(repo, "add", "-A")
    git_c(repo, "commit", "-qm", "repo-ai init", "--allow-empty")
    rec = W.ra("new", repo, "verify", "--record", "--json", *tc_for(name), *record_args)
    return repo, {"init_exit": init["exit"], "record_exit": rec["exit"], "record_s": rec["wall_s"],
                  "record_error": rec.get("error"),
                  "record_failures": ((rec.get("data") or {}).get("baseline_failures") or [])[:20]}


def reset(repo: Path) -> None:
    H.git(repo, "reset", "-q", "--hard", "HEAD")
    subprocess.run(["git", "clean", "-qfd", "-e", ".repo-ai"], cwd=repo, check=False)


def compact(run: dict) -> dict:
    data = run.get("data") or {}
    ev = data.get("evidence") or {}
    plan = data.get("plan") or {}
    rows = ev.get("results") or []
    return {
        "wall_s": run.get("wall_s"), "exit": run.get("exit"), "tree_unchanged": run.get("tree_unchanged"),
        "error": run.get("error"), "verdict": ev.get("verdict"), "confidence": plan.get("confidence"),
        "selected": [s.get("test") for s in plan.get("selected") or []][:50],
        "full_suite": (ev.get("full_suite") or {}).get("status"),
        "strategy": (ev.get("strategy") or {}).get("kind"), "reused": bool(ev.get("reused")),
        "processes": (ev.get("processes") or {}).get("total") if isinstance(ev.get("processes"), dict) else None,
        "fingerprint": ev.get("fingerprint"),
        "results": [{"test": r.get("test"), "status": r.get("status"), "baseline": r.get("baseline"),
                     "classification": r.get("classification"),
                     "failing_tests": sorted(r.get("failing_tests") or {})[:10] if isinstance(
                         r.get("failing_tests"), dict) else (r.get("failing_tests") or [])[:10]}
                    for r in rows][:200],
    }


def call(repo: Path, *args: str, stdin: str | None = None, timeout: float = 3600) -> dict:
    t = time.monotonic()
    p = subprocess.run([H.RA, *args], cwd=repo, env=H.env(), capture_output=True, text=True, input=stdin,
                       timeout=timeout)
    return {"exit": p.returncode, "stdout": p.stdout, "stderr": p.stderr[-1500:],
            "wall_s": round(time.monotonic() - t, 2)}


def verify(repo: Path, name: str, *extra: str, image: bool = True) -> dict:
    return compact(W.ra("new", repo, "verify", "--run", "--json", *tc_for(name, image), *extra))


def evidence(repo: Path) -> dict:
    r = call(repo, "evidence", "--json")
    try:
        d = json.loads(r["stdout"])
    except ValueError:
        return {"exit": r["exit"], "parse_error": r["stdout"][-300:] or r["stderr"][-300:]}
    rec = d.get("evidence") or {}
    return {"exit": r["exit"], "current": d.get("current"), "same_behaviour": d.get("same_behaviour"),
            "verdict": rec.get("verdict"), "fingerprint": rec.get("fingerprint")}


def gate(repo: Path, session: str) -> dict:
    """The gate's decision for this state with no earlier gate state (it
    stays silent for a change it has already reported once)."""
    g = repo / ".repo-ai" / "state" / "gate.json"
    if g.exists():
        g.unlink()
    r = call(repo, "verify", "--gate", stdin=json.dumps({"session_id": session}))
    out = r["stdout"].strip()
    try:
        d = json.loads(out) if out else {}
    except ValueError:
        d = {"unparsed": out[-300:]}
    return {"exit": r["exit"], "silent": not out, "decision": d.get("decision"),
            "message": (d.get("reason") or d.get("systemMessage") or "")[:300]}


def plan_status(repo: Path, name: str) -> dict:
    r = call(repo, "verify", "--json", "--test-command", H.CORPUS[name]["test_command"])
    try:
        d = json.loads(r["stdout"])
    except ValueError:
        return {"exit": r["exit"], "error": r["stderr"][-300:]}
    return {"exit": r["exit"], "evidence_status": d.get("evidence_status"),
            "changed_files": [c.get("path") if isinstance(c, dict) else c for c in d.get("changed_files") or []][:20]}


# ---------------------------------------------------------------------------
# validation: the project's own test files, alone, in its container
# ---------------------------------------------------------------------------
def files_truth(name: str, repo: Path, tests: list[str], timeout: float = 300) -> dict:
    from repo_ai import sandbox
    work = H.WORK / "tmp" / f"scen-{name}-{os.getpid()}-{threading.get_ident()}-{time.monotonic_ns()}"  # never reused
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(repo, work, symlinks=True, ignore=shutil.ignore_patterns(".repo-ai", "node_modules",
                                                                             "__pycache__"))
    try:
        runner = H.runner_for(name)
        lang = H.CORPUS[name]["lang"]
        ev = work / ".eval"
        ev.mkdir(exist_ok=True)
        driver = ev / ("driver.py" if lang == "python" else "driver.mjs")
        driver.write_text(H.DRIVER_PY if lang == "python" else H.DRIVER_NODE, "utf-8")
        spec = {"cwd": runner.cwd, "timeout": timeout, "env": runner.env,
                "runs": [{"test": t, "argv": runner.file_argv(t)} for t in tests]}
        (ev / "spec.json").write_text(json.dumps(spec), "utf-8")
        head = ["python"] if lang == "python" else ["node"]
        res = H.backend_for(name).run(
            [*head, f"/work/.eval/{driver.name}", "/work/.eval/spec.json", "/work/.eval/result.json"], work,
            limits=sandbox.Limits(timeout_s=7200, memory_mb=4096, cpus=2, pids=2048),
            toolchain=lang if lang == "node" else "python")
        try:
            return json.loads((ev / "result.json").read_text("utf-8"))
        except (OSError, ValueError) as exc:
            raise RuntimeError(f"{name}: driver failed: {res.stderr[-800:]}") from exc
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _fails(res: dict, test: str) -> bool:
    r = res.get(test) or {}
    return r.get("exit") not in (0, None)


def _hangs(res: dict, test: str) -> bool:
    """Not finished within the limit: killed (-9), or ended by the driver's
    SIGTERM at the limit (`node --test` handles it and exits with a code)."""
    r = res.get(test) or {}
    return r.get("exit") == -9 or (r.get("exit") not in (0, None) and float(r.get("dur") or 0) >= HANG_CHECK_S - 1)


# ---------------------------------------------------------------------------
# scenarios
# ---------------------------------------------------------------------------
class Rec:
    def __init__(self, name: str) -> None:
        self.name = name
        self.rows: list[dict] = []

    def add(self, sid: str, label: dict, **kw) -> dict:
        row = {"id": sid, "project": self.name, "label": label, **kw}
        self.rows.append(row)
        print(f"  {self.name} {sid}: valid={label.get('valid')} "
              + " | ".join(f"{r.get('verdict')} ({r.get('wall_s')}s)" for r in kw.get("runs") or []), flush=True)
        return row


def label(new_failure: bool, hang: bool, valid: bool, why: str = "", files: list[str] | None = None,
          **extra) -> dict:
    return {"new_failure": new_failure, "hang": hang, "valid": valid, "why_invalid": "" if valid else why,
            "files": files or [], **extra}


def guarded(rec: Rec, sid: str, fn) -> None:
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - one scenario's harness failure is recorded, not hidden
        rec.add(sid, label(False, False, False, f"harness error: {exc!r}"[:300]),
                traceback=traceback.format_exc()[-1500:])


def run_main(name: str, rec: Rec, pk: dict) -> None:
    """Scenarios on the unmodified base, one clone, in a fixed order (the
    state directory carries over, as in a real session)."""
    repo, setup = fresh(name, "main")
    rec.add("setup-main", label(False, False, True), setup=setup)
    M = change(name, pk["M"]) if pk["M"] else None
    M2 = change(name, pk["M2"]) if pk["M2"] else None
    P = change(name, pk["P"]) if pk["P"] else None
    aff = pk["M_affected"]

    def m_label(extra_files: list[str] | None = None) -> dict:
        res = files_truth(name, repo, aff)
        ok = any(_fails(res, t) for t in aff)
        return label(True, False, ok, "M's affected files pass in this state", aff + (extra_files or []))

    # U1: the failing change, staged
    def u1():
        H._apply(repo, M)
        H.git(repo, "add", "-A")
        lab = m_label()
        rec.add("U1-staged", lab, runs=[verify(repo, name)], evidence=evidence(repo), gate=gate(repo, "U1"))
        reset(repo)
    if M:
        guarded(rec, "U1-staged", u1)

    # U2: a new, untracked test file that fails
    def u2():
        t = pk["T"]
        new = new_test_name(t)
        (repo / new).write_text(snippet(repo, t, "fail", "u2", (repo / t).read_text("utf-8")).lstrip("\n"), "utf-8")
        files = [f for f in H.git(repo, "ls-files", "--cached", "--others", "--exclude-standard").split("\n") if f]
        collected = new in H.runner_for(name).test_files(files)
        res = files_truth(name, repo, [new])
        lab = label(True, False, collected and _fails(res, new),
                    "the new file is not collected by the command" if not collected else "the new file passes",
                    [new], new_file=new)
        rec.add("U2-untracked-test", lab, runs=[verify(repo, name)], evidence=evidence(repo), gate=gate(repo, "U2"))
        reset(repo)
    if pk["T"]:
        guarded(rec, "U2-untracked-test", u2)

    # U3/U4/U5: the changed source file of M deleted (worktree), deleted (staged), renamed (staged)
    def deletion(sid: str, how: str):
        f = pk["M_file"]
        if how == "worktree":
            (repo / f).unlink()
        elif how == "staged":
            H.git(repo, "rm", "-q", f)
        else:
            stem, ext = os.path.splitext(f)
            H.git(repo, "mv", f, f"{stem}_zzmoved{ext}")
        res = files_truth(name, repo, pk["base_passing"])
        bad = sorted(t for t in pk["base_passing"] if _fails(res, t))
        lab = label(True, False, bool(bad), "no test file fails without the file", bad)
        rec.add(sid, lab, runs=[verify(repo, name)], evidence=evidence(repo), gate=gate(repo, sid))
        reset(repo)
    if pk["M_file"]:
        guarded(rec, "U3-deleted", lambda: deletion("U3-deleted", "worktree"))
        guarded(rec, "U4-deleted-staged", lambda: deletion("U4-deleted-staged", "staged"))
        guarded(rec, "U5-renamed-staged", lambda: deletion("U5-renamed-staged", "rename"))

    # U6: a passing change staged, the failing change on top in the worktree only
    def u6():
        H._apply(repo, P)
        H.git(repo, "add", "-A")
        H._apply(repo, M)
        rec.add("U6-index-differs", m_label(), runs=[verify(repo, name)], evidence=evidence(repo),
                gate=gate(repo, "U6"))
        reset(repo)
    if M and P:
        guarded(rec, "U6-index-differs", u6)

    # C1/C2: evidence of a passing state never vouches for the failing one; reuse never crosses states
    p_wall: list[float] = []

    def c1():
        H._apply(repo, P)
        first = verify(repo, name)
        p_wall.append(first["wall_s"] or 0)
        reset(repo)
        H._apply(repo, M)
        rec.add("C1-stale-evidence", m_label(), runs=[], context=[first], evidence=evidence(repo),
                gate=gate(repo, "C1"), plan=plan_status(repo, name),
                note="context[0] is the run of the passing change P; the checks (evidence, gate) are for M")
        reset(repo)

    def c2():
        H._apply(repo, M)
        a = verify(repo, name)
        reset(repo)
        H._apply(repo, P)
        b = verify(repo, name)
        reset(repo)
        H._apply(repo, M)
        lab = m_label()
        c = verify(repo, name)  # reuse allowed
        rec.add("C2-reuse-after-revert", lab, runs=[c], context=[a, b], evidence=evidence(repo),
                gate=gate(repo, "C2"))
        reset(repo)
    if M and P:
        guarded(rec, "C1-stale-evidence", c1)
        guarded(rec, "C2-reuse-after-revert", c2)

    # C3: two runs of the same failing state at once
    def c3():
        H._apply(repo, M2)
        a2 = (H.load(name, "truth").get(M2["id"]) or {}).get("affected") or []
        res = files_truth(name, repo, a2)
        lab = label(True, False, any(_fails(res, t) for t in a2), "M2's affected files pass", a2)
        out: list[dict] = [{}, {}]

        def go(i: int) -> None:
            out[i] = verify(repo, name, "--rerun")
        th = [threading.Thread(target=go, args=(i,)) for i in range(2)]
        for t in th:
            t.start()
        for t in th:
            t.join()
        rec.add("C3-concurrent-same-state", lab, runs=out, evidence=evidence(repo), gate=gate(repo, "C3"))
        reset(repo)
    if M2:
        guarded(rec, "C3-concurrent-same-state", c3)

    # C4: two linked worktrees, a passing and a failing state, verified at once
    def c4():
        wt = repo.parent / "main-wt2"
        if wt.exists():
            shutil.rmtree(wt)
        H.git(repo, "worktree", "add", "-q", "--detach", str(wt), "HEAD")
        H._install_metadata(wt)
        W.ra("new", wt, "init", "--agent", "none", "-q")  # a linked worktree has its own state directory
        reset(wt)  # init leaves the committed files as they are; anything else it wrote is not the change
        H._apply(repo, P)
        H._apply(wt, M)
        lab = m_label_at(wt)
        out: list[dict] = [{}, {}]

        def go(i: int, where: Path) -> None:
            out[i] = verify(where, name, "--rerun")
        th = [threading.Thread(target=go, args=(0, repo)), threading.Thread(target=go, args=(1, wt))]
        for t in th:
            t.start()
        for t in th:
            t.join()
        rec.add("C4-two-worktrees", lab, runs=[out[1]], context=[out[0]], evidence=evidence(wt),
                gate=gate(wt, "C4"), note="runs[0] is the failing worktree; context[0] the passing one (P)",
                passing_side_evidence=evidence(repo))
        reset(repo)
        H.git(repo, "worktree", "remove", "--force", str(wt))

    def m_label_at(where: Path) -> dict:
        res = files_truth(name, where, aff)
        return label(True, False, any(_fails(res, t) for t in aff), "M's affected files pass", aff)
    if M and P:
        guarded(rec, "C4-two-worktrees", c4)

    # C5: the failing change written while a run of the passing one is in progress
    def c5():
        H._apply(repo, P)
        delay = 0.4 * (p_wall[0] if p_wall else 5.0)
        out: dict = {}

        def go() -> None:
            out["run"] = verify(repo, name, "--rerun")
        th = threading.Thread(target=go)
        th.start()
        time.sleep(delay)
        H._apply(repo, M)
        edited_at = delay
        th.join()
        lab = m_label()
        after = verify(repo, name)  # the final state, reuse allowed
        rec.add("C5-edit-during-run", lab, runs=[after], context=[out.get("run") or {}], edit_after_s=edited_at,
                evidence=evidence(repo), gate=gate(repo, "C5"),
                note="context[0]: the run the edit landed in; runs[0]: a run of the final state (reuse allowed)")
        reset(repo)
    if M and P:
        guarded(rec, "C5-edit-during-run", c5)

    # C8: the failing change committed; verified against the original base
    def c8():
        base = H.git(repo, "rev-parse", "HEAD").strip()
        H._apply(repo, M)
        H.git(repo, "add", "-A")
        git_c(repo, "commit", "-qm", "zz: committed failing change")
        lab = m_label()
        against_base = verify(repo, name, "--base", base)
        head_rel = verify(repo, name)
        rec.add("C8-committed-change", lab, runs=[against_base], head_relative=head_rel,
                note="runs[0]: --base <original base>; head_relative: the default (HEAD), informational")
        H.git(repo, "reset", "-q", "--hard", base)
    if M:
        guarded(rec, "C8-committed-change", c8)

    # H1: a test that hangs; H2: a hang in the first file and a failure in the last
    def h1():
        t = pk["T"]
        inject(repo, t, "hang", "h1")
        res = files_truth(name, repo, [t], timeout=HANG_CHECK_S)
        rec.add("H1-hang", label(False, True, _hangs(res, t), "the file finishes", [t]), runs=[verify(repo, name)],
                evidence=evidence(repo), gate=gate(repo, "H1"))
        reset(repo)

    def h2():
        hf, ff = pk["Hf"], pk["Ff"]
        inject(repo, hf, "hang", "h2")
        inject(repo, ff, "fail", "f2")
        res = files_truth(name, repo, [hf, ff], timeout=HANG_CHECK_S)
        ok = _hangs(res, hf) and _fails(res, ff) and not _hangs(res, ff)
        rec.add("H2-hang-then-failure", label(True, True, ok, "construction did not validate", [ff], hung=[hf]),
                runs=[verify(repo, name)], evidence=evidence(repo), gate=gate(repo, "H2"))
        reset(repo)
    if pk["T"]:
        guarded(rec, "H1-hang", h1)
    if pk["Hf"]:
        guarded(rec, "H2-hang-then-failure", h2)

    # A2: the failing and the passing change without the project's dependency image
    def a2(sid: str, c: dict, failing: bool):
        H._apply(repo, c)
        lab = m_label() if failing else label(False, False, True)
        rec.add(sid, lab, runs=[verify(repo, name, "--rerun", image=False)])
        reset(repo)
    if H.CORPUS[name].get("image") and M and P:
        guarded(rec, "A2-no-deps-failing", lambda: a2("A2-no-deps-failing", M, True))
        guarded(rec, "A2-no-deps-passing", lambda: a2("A2-no-deps-passing", P, False))

    # C6 (last: it damages the state directory): every verify state file cut in half, then M
    def c6():
        H._apply(repo, P)
        verify(repo, name)
        reset(repo)
        state = repo / ".repo-ai" / "state"
        cut = []
        for f in sorted(state.rglob("*.json")):
            if f.is_file() and f.name != "config.json":
                data = f.read_bytes()
                f.write_bytes(data[: len(data) // 2])
                cut.append(str(f.relative_to(state)))
        H._apply(repo, M)
        lab = m_label()
        rec.add("C6-corrupted-state", lab, runs=[verify(repo, name)], evidence=evidence(repo),
                gate=gate(repo, "C6"), truncated=cut[:100], truncated_n=len(cut))
        reset(repo)
    if M and P:
        guarded(rec, "C6-corrupted-state", c6)


def run_based(name: str, rec: Rec, pk: dict) -> None:
    """Scenarios whose *base* contains an injected test (committed before
    `init` and `--record`)."""
    M = change(name, pk["M"]) if pk["M"] else None
    P = change(name, pk["P"]) if pk["P"] else None
    t = pk["T"]

    # S1/S2: a test already failing at the base; then an unrelated change, and a new failure in the same file
    def s12():
        repo, setup = fresh(name, "base-fail", lambda r: inject(r, t, "fail", "b1"))
        res = files_truth(name, repo, [t])
        base_ok = _fails(res, t)
        rec.add("setup-base-fail", label(False, False, base_ok, "the injected test passes at the base"), setup=setup)
        if P:
            H._apply(repo, P)
            rec.add("S1-preexisting-unrelated", label(False, False, base_ok, "base injection did not fail", [],
                                                      preexisting=[t]),
                    runs=[verify(repo, name)])
            reset(repo)
        # the second failure alone must fail on the pristine file (validation without the base injection)
        probe = repo.parent / "s2-probe"
        if probe.exists():
            shutil.rmtree(probe)
        shutil.copytree(repo, probe, symlinks=True, ignore=shutil.ignore_patterns(".repo-ai", "node_modules"))
        H.git(probe, "checkout", "-q", "HEAD~2", "--", t)  # the file before the base injection
        inject(probe, t, "fail", "f2")
        ok2 = _fails(files_truth(name, probe, [t]), t)
        shutil.rmtree(probe, ignore_errors=True)
        inject(repo, t, "fail", "f2")
        rec.add("S2-new-failure-in-failing-file", label(True, False, base_ok and ok2, "construction did not validate",
                                                         [t], preexisting=[t]),
                runs=[verify(repo, name)], evidence=evidence(repo), gate=gate(repo, "S2"))
        reset(repo)
    if t:
        guarded(rec, "S1/S2", s12)

    # S3: a test failing at the base in the file M breaks
    def s3():
        a = pk["M_affected"][0]
        repo, setup = fresh(name, "base-fail-affected", lambda r: inject(r, a, "fail", "b3"))
        base_ok = _fails(files_truth(name, repo, [a]), a)
        H._apply(repo, M)
        # M's content for `a` is unchanged (M touches sources), so the file keeps the base injection
        rec.add("S3-mutation-in-failing-file", label(True, False, base_ok, "base injection did not fail", [a],
                                                      preexisting=[a]),
                runs=[verify(repo, name)], evidence=evidence(repo), gate=gate(repo, "S3"), setup=setup)
        reset(repo)
    if M and pk["M_affected"] and not set(M["files"]) & {pk["M_affected"][0]}:
        guarded(rec, "S3-mutation-in-failing-file", s3)

    # S4/S5: a flaky test at the base; an unrelated change, and the failing change, three runs each
    def s45():
        ft = t if t not in pk["M_affected"] else pk["T2"]
        repo, setup = fresh(name, "base-flaky", lambda r: inject(r, ft, "flaky", "b4"))
        rec.add("setup-base-flaky", label(False, False, True), setup=setup, flaky_file=ft)
        if P:
            H._apply(repo, P)
            rec.add("S4-flaky-unrelated", label(False, False, True, files=[], flaky=[ft]),
                    runs=[verify(repo, name, "--rerun") for _ in range(FLAKY_RUNS)])
            reset(repo)
        if M:
            H._apply(repo, M)
            aff = pk["M_affected"]
            res = files_truth(name, repo, aff)
            rec.add("S5-flaky-and-failing", label(True, False, any(_fails(res, x) for x in aff if x != ft),
                                                    "M's files pass", aff, flaky=[ft]),
                    runs=[verify(repo, name, "--rerun") for _ in range(FLAKY_RUNS)])
            reset(repo)
    if t and (t not in pk["M_affected"] or pk["T2"]):
        guarded(rec, "S4/S5", s45)

    # H3: the first file already hangs at the base; the change makes the last file fail
    def h3():
        hf, ff = pk["Hf"], pk["Ff"]
        repo, setup = fresh(name, "base-hang", lambda r: inject(r, hf, "hang", "b5"),
                            record_args=("--timeout", H3_TIMEOUT))
        rec.add("setup-base-hang", label(False, False, True), setup=setup)
        inject(repo, ff, "fail", "f5")
        res = files_truth(name, repo, [hf, ff], timeout=HANG_CHECK_S)
        ok = _hangs(res, hf) and _fails(res, ff) and not _hangs(res, ff)
        rec.add("H3-base-hang-then-failure", label(True, False, ok, "construction did not validate", [ff],
                                                    preexisting_hang=[hf]),
                runs=[verify(repo, name, "--timeout", H3_TIMEOUT)], evidence=evidence(repo), gate=gate(repo, "H3"))
        reset(repo)
    if pk["Hf"]:
        guarded(rec, "H3-base-hang-then-failure", h3)


def run_control(name: str, rec: Rec) -> None:
    """A1: a runner verify cannot split (Jest, Vitest, ...). The label comes
    from the project's own full suite in its container, per change."""
    from repo_ai.verify import isolate
    from repo_ai.verify.execute import Executor
    runner = H.runner_for(name)
    repo, setup = fresh(name, "control")
    rec.add("setup-control", label(False, False, True), setup=setup, runner_kind=runner.kind)

    def native_exit() -> dict:
        ws = isolate.materialize(repo, label="scen-native")
        try:
            ex = Executor(H.backend_for(name), repo, python="python", node="node").in_workspace(ws)
            res = ex.run(runner.full or shlex.split(runner.command), cwd=runner.cwd, env=runner.env, timeout_s=1800,
                         toolchain="node" if H.CORPUS[name]["lang"] == "node" else "python")
            return {"exit": res.exit_code, "timed_out": res.timed_out}
        finally:
            ws.cleanup()
    base = native_exit()
    rec.add("A1-base", label(False, False, base["exit"] == 0, "the native suite fails at the base"), native=base)
    if base["exit"] != 0:
        return
    nf = npass = 0
    for c in H.load(name, "changes"):
        if nf >= 4 and npass >= 2:
            break
        H._apply(repo, c)
        nat = native_exit()
        failing = nat["exit"] != 0 and not nat["timed_out"]
        if (failing and nf < 4) or (not failing and not nat["timed_out"] and npass < 2):
            rec.add(f"A1-{'failing' if failing else 'passing'}-{c['id']}", label(failing, False, True, files=[]),
                    runs=[verify(repo, name)], native=nat, evidence=evidence(repo))
            nf, npass = nf + failing, npass + (not failing)
        reset(repo)


def main() -> int:
    names = [a for a in sys.argv[1:] if not a.startswith("--")]
    for name in names:
        print(f"== {name} at {time.strftime('%Y-%m-%dT%H:%M:%S')}", flush=True)
        path = H.WORK / f"scenarios-{name}.json"
        earlier = json.loads(path.read_text("utf-8")) if path.exists() else None
        rec = Rec(name)
        out: dict = {"project": name, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                     "engine": subprocess.run([H.RA, "--version"], capture_output=True, text=True).stdout.strip()}
        try:
            if H.runner_for(name).kind == "opaque" or not H.load(name, "setup")["tests"]:  # Amendment 5a
                run_control(name, rec)
            else:
                pk = picks(name)
                out["picks"] = {k: v for k, v in pk.items() if k != "base_passing"}
                run_main(name, rec, pk)
                run_based(name, rec, pk)
        except Exception as exc:  # noqa: BLE001
            out["error"] = repr(exc)[:500]
            out["traceback"] = traceback.format_exc()[-2000:]
        out["rows"] = rec.rows
        out["finished"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        if earlier is not None:  # a re-run never erases an earlier attempt
            out["_superseded"] = [*(earlier.pop("_superseded", []) or []), earlier]
        path.write_text(json.dumps(out, indent=1), "utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
