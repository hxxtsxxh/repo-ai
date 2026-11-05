"""Run the abc-v5 decision rules on the calibration candidates, fully offline (no model, no provider, $0).

  python run_offline.py [--out results/calibration.json] [--tasks a,b] [--unsealed]

Needs an interpreter with pytest and repo-ai's dependencies (pathspec); repo-ai itself is imported from
<worktree>/src via PYTHONPATH, never from an installed copy. Arms (see manifest.json "arms"):

  A        exit 0 of test_command in the candidate's own workspace (from the sealed grader's A-view)
  A0       same, shipped tests only (no developer acceptance tests)
  A_clean  only write_paths files overlaid on a clean W (from the grader's frozen view)
  B        `repo-ai do --agent replay --replay P --run` on a git repo of W, then `repo-ai coverage`
  B_perm   process controls only: B with --allow-write widened to the files the candidate touched (probes the
           frozen-acceptance gate rather than the path gate)
  B_plus / A_plus / A_plus_plus   exploratory directed vs undirected follow-up tests (PREREGISTRATION 5.4)

The only repo-ai agent used is `replay` (an explicitly simulated proposal). Any argv containing a live-provider flag
or another agent is refused before it is executed.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKTREE = HERE.parent.parent
SRC = WORKTREE / "src"
sys.path.insert(0, str(HERE))
import grade as G  # noqa: E402
import make_manifest as MM  # noqa: E402

SEED = MM.SEED
VERIFIED = {"VERIFIED_FAIL_TO_PASS", "VERIFIED_PRESERVED"}
FORBIDDEN = ("--allow-live-provider", "--tournament", "--provider-executable", "--role")


# ---------------------------------------------------------------- repo-ai CLI (replay only)
def repo_ai(args: list[str], home: Path, timeout: int = 300) -> subprocess.CompletedProcess:
    if any(a in FORBIDDEN for a in args) or ("--agent" in args and args[args.index("--agent") + 1] != "replay"):
        raise RuntimeError(f"refused: run_offline only drives the replay agent: {args}")
    env = {k: v for k, v in os.environ.items() if not k.startswith(("REPO_AI_", "CLAUDE", "AI_AGENT", "CODEX", "GEMINI"))}
    env.update(PYTHONPATH=str(SRC), REPO_AI_NO_BACKGROUND="1", HOME=str(home), PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run([sys.executable, "-m", "repo_ai", *args], capture_output=True, text=True, env=env,
                          timeout=timeout)


def git_repo(path: Path) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "abc-v5", "GIT_AUTHOR_EMAIL": "abc-v5@example.invalid",
           "GIT_COMMITTER_NAME": "abc-v5", "GIT_COMMITTER_EMAIL": "abc-v5@example.invalid",
           "GIT_AUTHOR_DATE": "2026-10-29T00:00:00Z", "GIT_COMMITTER_DATE": "2026-10-29T00:00:00Z"}
    for cmd in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "W baseline"]):
        subprocess.run(["git", *cmd], cwd=path, check=True, capture_output=True, env=env)


def _json(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return None


def b_arm(task: dict, task_id: str, files: dict[str, str], reqs: dict, home: Path, work: Path,
          extra_dirs: tuple[Path, ...] = (), allow: list[str] | None = None) -> dict:
    """Run repo-ai do (replay) + coverage on one candidate; returns the decision and the evidence it rests on."""
    repo = work / "repo"
    G.materialize_w(task_id, repo, extra_dirs=extra_dirs)
    git_repo(repo)
    edits = []
    for rel, text in sorted(files.items()):
        p = repo / rel
        before = p.read_bytes() if p.is_file() else b""
        if before.decode("utf-8", "replace") != text:
            edits.append({"path": rel, "before_sha256": hashlib.sha256(before).hexdigest(), "after": text})
    if not edits:   # the no-op candidate: submit the unchanged write path, which repo-ai must refuse
        rel = task["write_paths"][0]
        edits.append({"path": rel, "before_sha256": hashlib.sha256((repo / rel).read_bytes()).hexdigest(),
                      "after": (repo / rel).read_text()})
    proposal = work / "proposal.json"
    proposal.write_text(json.dumps({"schema": "repo-ai.replay/1", "label": "abc-v5 authored candidate (simulated)",
                                    "edits": edits}))
    req_path = work / "requirements.json"
    req_path.write_text(json.dumps(reqs))
    allow = allow if allow is not None else task["write_paths"]
    argv = ["do", task["prompt"], "-C", str(repo), "--agent", "replay", "--replay", str(proposal), "--run",
            "--test-command", task["test_command"], "--max-seconds", "180", "--json"]
    for w in allow:
        argv += ["--allow-write", w]
    t0 = time.monotonic()
    do = repo_ai(argv, home)
    out: dict = {"do_exit": do.returncode, "seconds": round(time.monotonic() - t0, 1)}
    data = _json(do.stdout)
    if not isinstance(data, dict) or "id" not in data:
        out.update(decision="REJECT", why="proposal refused / no mission",
                   refusal=" | ".join(ln for ln in (do.stderr + do.stdout).strip().splitlines()
                                      if "repo-ai doctor" not in ln)[-400:])
        return out
    out.update(mission=data["id"], state=data.get("state"), verdict=data.get("effective_verdict"),
               freshness=data.get("freshness"), claims_headline=(data.get("claims") or {}).get("headline"),
               baseline=(data.get("baseline") or {}).get("outcomes"),
               candidate=(data.get("candidate") or {}).get("outcomes"))
    cov = repo_ai(["coverage", data["id"], "-C", str(repo), "--requirements", str(req_path), "--json"], home)
    report = _json(cov.stdout)
    out["coverage_exit"] = cov.returncode
    if isinstance(report, dict) and "headline" in report:
        out["coverage"] = {"headline": report["headline"],
                           "rows": [{"text": r["text"], "kind": r["kind"], "status": r["status"]}
                                    for r in report["requirements"]],
                           "follow_up_test_needed": report["follow_up_test_needed"]}
    rows = out.get("coverage", {}).get("rows", [])
    out["named_unverified"] = sorted({r["text"].split(":", 1)[0] for r in rows if r["status"] not in VERIFIED})
    if out["state"] != "COMPLETE" or out["verdict"] != "PASS":
        out.update(decision="REJECT", why=f"state {out['state']} / verdict {out['verdict']}")
    elif "coverage" not in out:
        out.update(decision="ABSTAIN", why="coverage did not produce a report: " + cov.stderr.strip()[-200:])
    elif any(r["status"] in ("FAILING", "MISSING_TEST") for r in rows):
        out.update(decision="REJECT", why="a mapped test is FAILING or MISSING_TEST")
    elif out["coverage"]["headline"] == "ACCEPTANCE_MAPPED_ALL" and out["freshness"] == "fresh":
        out.update(decision="ACCEPT", why="PASS and every requirement verified")
    else:
        out.update(decision="ABSTAIN", why="PASS but coverage " + out["coverage"]["headline"])
    return out


# ---------------------------------------------------------------- follow-up pool helpers
def _blocks(text: str, lang: str) -> tuple[str, dict[str, str]]:
    starts = r"^def (test_\w+)\(" if lang == "python" else r"^test\('([^']+)'"
    lines = text.splitlines(keepends=True)
    idx = [(i, re.match(starts, ln).group(1)) for i, ln in enumerate(lines) if re.match(starts, ln)]
    header = "".join(lines[:idx[0][0]]) if idx else text
    blocks = {}
    for n, (i, name) in enumerate(idx):
        end = idx[n + 1][0] if n + 1 < len(idx) else len(lines)
        blocks[name] = "".join(lines[i:end])
    return header, blocks


def followup_dir(task_id: str, task: dict, req_ids: list[str], dest: Path) -> list[str]:
    """Write a filtered copy of the follow-up pool holding only the tests for req_ids; return their names."""
    pool = G.TASKS / task_id / "followup"
    fmap = json.loads((pool / "map.json").read_text())
    wanted = [t for r in req_ids for t in fmap.get(r, [])]
    dest.mkdir(parents=True, exist_ok=True)
    for p in sorted(pool.iterdir()):
        if p.name == "map.json" or not p.is_file():
            continue
        header, blocks = _blocks(p.read_text(), task["language"])
        keep = [blocks[n] for n in blocks if n in wanted]
        if keep:
            (dest / p.name).write_text(header + "".join(keep).rstrip("\n") + "\n")
    return wanted


def a_with_followup(task_id: str, task: dict, files: dict[str, str], req_ids: list[str], work: Path) -> bool:
    fdir = work / "fu"
    followup_dir(task_id, task, req_ids, fdir)
    tree = work / "tree"
    G.materialize_w(task_id, tree, extra_dirs=(fdir,))
    G.overlay(tree, files)
    return G.run_suite(task, tree, None, developer=True)["exit"] == 0


def b_plus_map(reqs: dict, b: dict, task_id: str) -> dict:
    fmap = json.loads((G.TASKS / task_id / "followup" / "map.json").read_text())
    base = b.get("baseline") or {}
    new = []
    for r in reqs["requirements"]:
        rid = r["text"].split(":", 1)[0]
        tests = list(r["tests"])
        if rid in b["named_unverified"]:
            if r["kind"] == "change":   # drop mapped tests repo-ai observed passing at baseline
                tests = [t for t in tests if not any(k.endswith("::" + t) and v == "pass" for k, v in base.items())]
            tests += fmap.get(rid, [])
        new.append({**r, "tests": tests})
    return {"schema": reqs["schema"], "requirements": new}


# ---------------------------------------------------------------- main
def run(tasks: list[str], sealed: bool) -> dict:
    rows = []
    with tempfile.TemporaryDirectory(prefix="abc5-offline-") as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        for task_id in tasks:
            task = G.load_task(task_id)
            reqs = json.loads((G.TASKS / task_id / "requirements.json").read_text())
            all_ids = [r["id"] for r in task["requirements"]]
            for name, meta in sorted(G.load_candidates(task_id).items()):
                files = G.candidate_files(task_id, name)
                work = Path(tmp) / f"{task_id}--{name}"
                g = G.grade(task_id, files, sealed=sealed)
                row = {"task": task_id, "candidate": name, "kind": meta["kind"], "stratum": meta["stratum"],
                       "label": g["label"], "violated_requirements": g.get("violated_requirements", []),
                       "A": "ACCEPT" if g["a_view"]["green"] else "REJECT",
                       "A_clean": "ACCEPT" if g["a_clean_green"] else "REJECT"}
                shipped = {k: v for k, v in files.items()
                           if k in task["write_paths"] or (G.TASKS / task_id / "repo" / k).exists()}
                t0 = work / "a0"
                G.materialize_w(task_id, t0, acceptance=False)
                G.overlay(t0, shipped)
                row["A0"] = "ACCEPT" if G.run_suite(task, t0, None, developer=True)["exit"] == 0 else "REJECT"
                b = b_arm(task, task_id, files, reqs, home, work / "b")
                row["B"] = b["decision"]
                row["B_detail"] = b
                if meta["stratum"] == "process" and set(files) - set(task["write_paths"]):
                    perm = b_arm(task, task_id, files, reqs, home, work / "bperm", allow=sorted(files))
                    row["B_perm"] = perm["decision"]
                    row["B_perm_detail"] = {k: perm.get(k) for k in ("decision", "why", "refusal", "verdict")}
                named = [r for r in b.get("named_unverified", [])]
                row["actionable"] = bool(set(named) & set(row["violated_requirements"])) if named else False
                k = len(named) if b["decision"] == "ABSTAIN" else 0
                if k:
                    fu = work / "bplus-fu"
                    followup_dir(task_id, task, named, fu)
                    bp = b_arm(task, task_id, files, b_plus_map(reqs, b, task_id), home, work / "bplus",
                               extra_dirs=(fu,))
                    row["B_plus"] = bp["decision"]
                    row["B_plus_detail"] = {kk: bp.get(kk) for kk in ("decision", "why", "verdict", "coverage")}
                    pick = sorted(random.Random(f"{SEED}:{task_id}:{name}").sample(all_ids, k))
                    row["A_plus_requirements"] = pick
                    row["A_plus"] = "ACCEPT" if a_with_followup(task_id, task, files, pick, work / "aplus") else "REJECT"
                else:
                    row["B_plus"], row["A_plus"] = row["B"], row["A"]
                row["followup_tests_B_plus"] = k
                row["A_plus_plus"] = ("ACCEPT" if a_with_followup(task_id, task, files, all_ids, work / "aplusplus")
                                      else "REJECT")
                rows.append(row)
                print(f"{task_id:15} {name:19} {row['label']:11} A={row['A']:6} A0={row['A0']:6} "
                      f"Ac={row['A_clean']:6} B={row['B']:7} B+={row['B_plus']:7} A+={row['A_plus']:6} "
                      f"A++={row['A_plus_plus']:6} {b.get('why', '')}", flush=True)
                shutil.rmtree(work, ignore_errors=True)
    return {"rows": rows}


def summarize(rows: list[dict]) -> dict:
    sys.path.insert(0, str(SRC))
    from repo_ai import stats
    arms = ["A", "A0", "A_clean", "B", "B_plus", "A_plus", "A_plus_plus"]
    labels = ["CORRECT", "FALSE_GREEN", "FAIL", "INVALID"]
    conf = {a: {lab: {} for lab in labels} for a in arms}
    for r in rows:
        for a in arms:
            d = conf[a][r["label"]]
            d[r[a]] = d.get(r[a], 0) + 1
    fg = [r for r in rows if r["label"] == "FALSE_GREEN"]
    ok = [r for r in rows if r["label"] == "CORRECT"]

    def rate(sub, arm, val="ACCEPT"):
        return {"k": sum(r[arm] == val for r in sub), "n": len(sub)}

    by_stratum = {s: {a: rate([r for r in fg if r["stratum"] == s], a) for a in arms}
                  for s in sorted({r["stratum"] for r in fg})}
    draw = json.loads((HERE / "manifest.json").read_text()).get("primary_candidate_draw", {}) \
        if (HERE / "manifest.json").exists() else {}
    prim = {}
    for t, cand in draw.items():
        r = next((x for x in rows if x["task"] == t and x["candidate"] == cand), None)
        ref = next((x for x in rows if x["task"] == t and x["candidate"] == "reference"), None)
        if r and ref:
            prim[t] = {"decoy": cand, "A_accepts_decoy": r["A"] == "ACCEPT", "B_accepts_decoy": r["B"] == "ACCEPT",
                       "B_accepts_reference": ref["B"] == "ACCEPT", "B_plus_accepts_decoy": r["B_plus"] == "ACCEPT",
                       "A_plus_accepts_decoy": r["A_plus"] == "ACCEPT",
                       "B_plus_accepts_reference": ref["B_plus"] == "ACCEPT"}
    # compare_clustered expects success pairs; 'success' here = NOT accepting the false green
    h1 = stats.compare_clustered({t: [(int(not p["A_accepts_decoy"]), int(not p["B_accepts_decoy"]))]
                                  for t, p in prim.items()}, label_a="A", label_b="B")
    h2 = stats.compare_clustered({t: [(int(not p["A_plus_accepts_decoy"]), int(not p["B_plus_accepts_decoy"]))]
                                  for t, p in prim.items()}, label_a="A_plus", label_b="B_plus")
    j = {t: int(p["B_accepts_reference"] and not p["B_accepts_decoy"]) -
         int(p["B_accepts_decoy"] and not p["B_accepts_reference"]) for t, p in prim.items()}
    jp = {t: int(p["B_plus_accepts_reference"] and not p["B_plus_accepts_decoy"]) -
          int(p["B_plus_accepts_decoy"] and not p["B_plus_accepts_reference"]) for t, p in prim.items()}
    non_fg_b = [r for r in fg if r["B"] != "ACCEPT"]
    return {
        "confusion": conf,
        "false_green_acceptance": {a: rate(fg, a) for a in arms},
        "false_green_acceptance_by_stratum": by_stratum,
        "correct_non_acceptance": {a: {"k": sum(r[a] != "ACCEPT" for r in ok), "n": len(ok)} for a in arms},
        "correct_B_breakdown": {r["task"]: r["B"] + " (" + r["B_detail"].get("why", "") + ")" for r in ok},
        "actionability_B": {"k": sum(r["actionable"] for r in non_fg_b), "n": len(non_fg_b),
                            "meaning": "false greens B did not accept whose violated requirement B named as unverified"},
        "followup_tests_used": {"B_plus": sum(r["followup_tests_B_plus"] for r in rows),
                                "A_plus_plus_per_candidate": "all requirements"},
        "primary_pairs": prim,
        "H1_pilot": {**h1, "note": "calibration pilot (n=4 < MIN_PAIRS=10): never 'supported'"},
        "H2_pilot": {**h2, "note": "calibration pilot (n=4 < MIN_PAIRS=10): never 'supported'"},
        "J_task_level_B": j, "J_task_level_B_plus": jp,
        "B_perm_process_controls": {f"{r['task']}/{r['candidate']}": r.get("B_perm_detail") for r in rows
                                    if "B_perm" in r},
    }


def main() -> int:
    args = sys.argv[1:]
    out = HERE / "results" / "calibration.json"
    if "--out" in args:
        out = Path(args[args.index("--out") + 1])
    tasks = MM.task_ids()
    if "--tasks" in args:
        tasks = args[args.index("--tasks") + 1].split(",")
    sealed = "--unsealed" not in args
    t0 = time.monotonic()
    result = run(tasks, sealed)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=WORKTREE, capture_output=True, text=True).stdout.strip()
    node = subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip()
    manifest = json.loads((HERE / "manifest.json").read_text()) if (HERE / "manifest.json").exists() else {}
    report = {
        "study": "abc-v5", "split": "calibration", "confirmatory": False,
        "note": "Calibration only: synthetic tasks, one author for every role, authored candidates. Not evidence of "
                "lift or of safety; never pooled with confirmatory data. No model or provider was invoked "
                "(repo-ai replay agent only, $0). Mission ids and seconds vary between runs; decisions are "
                "deterministic.",
        "environment": {"repo_ai_git_head": head, "python": platform.python_version(), "node": node,
                        "platform": platform.system(), "sealed": sealed,
                        "manifest_content_sha256": manifest.get("content_sha256")},
        "summary": summarize(result["rows"]),
        "rows": result["rows"],
        "wall_seconds": round(time.monotonic() - t0, 1),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print("wrote", out)
    s = report["summary"]
    print("false-green acceptance:", {a: f"{v['k']}/{v['n']}" for a, v in s["false_green_acceptance"].items()})
    print("correct non-acceptance:", {a: f"{v['k']}/{v['n']}" for a, v in s["correct_non_acceptance"].items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
