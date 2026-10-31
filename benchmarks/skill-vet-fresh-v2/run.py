"""skill-vet-fresh-v2 harness, v1's unchanged (see PREREGISTRATION.md). $0: no model, no network.

Skill cases go through the path autopilot takes for a nominated local skill: quarantine, firewall inspection,
`capbundle.assess`, then `autonomy.decide("SAFE_AUTO", ..., nominated=True)`. Every case, skill or plugin, also
goes through `repo-ai skills vet <dir> --json` (the user-facing verdict, which includes plugin inspection).

    python benchmarks/skill-vet-fresh-v2/run.py [--out results/run-1.json]
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))

from repo_ai import autonomy, capbundle, firewall  # noqa: E402

SKILL_STRATA = {"H-text", "H-code", "B-skill"}
HARMFUL = {"H-text", "H-code", "H-plugin"}


def skill_case(case: Path, store: Path) -> dict:
    name = case.name
    dest, files, prior = firewall.quarantine_local(case, name, store=store)
    cand = {"id": f"local/{name}@{firewall.content_hash(files)[:12]}", "name": name, "provider": "local",
            "owner": "", "repo": "", "path": name, "commit": "", "stars": 0, "quarantine": str(dest)}
    report = firewall.inspect(dest, files, cand, {}, prior)
    assessment = capbundle.assess(dest, report, name)
    decision = autonomy.decide("SAFE_AUTO", assessment, nominated=True)
    return {"firewall_verdict": report.verdict, "firewall_complete": report.complete,
            "findings": sorted({f"{f.severity}:{f.category}/{f.rule}" for f in report.findings}),
            "inert": assessment["inert"], "installable": assessment["installable"],
            "surfaces": assessment["surfaces"], "safe_auto_action": decision["action"]}


def vet_case(case: Path, repo: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in {"AI_AGENT", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"}}
    env["PYTHONPATH"] = str(ROOT / "src")
    proc = subprocess.run([sys.executable, "-m", "repo_ai", "skills", "vet", str(case), "--json"], cwd=repo,
                          env=env, capture_output=True, text=True, timeout=300)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {"vet_verdict": "INVALID", "vet_exit": proc.returncode, "vet_error": (proc.stderr or proc.stdout)[-400:]}
    plugin = data.get("plugin") or {}
    return {"vet_verdict": data.get("verdict"), "vet_exit": proc.returncode,
            "plugin_verdict": plugin.get("verdict"),
            "plugin_findings": sorted({f"{f.get('severity')}:{f.get('rule')}" for f in plugin.get("findings") or []}
                                      | {f"{f.get('severity')}:{f.get('rule')}" for c in plugin.get("components") or []
                                         for f in c.get("findings") or []}),
            "skill_verdicts": sorted({str(s.get("verdict")) for s in data.get("skills") or []
                                      if isinstance(s, dict)})}


def make_repo(base: Path) -> Path:
    repo = base / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("x = 1\n")
    git = ["git", "-c", "user.email=e@example.com", "-c", "user.name=eval"]
    subprocess.run([*git, "init", "-q"], cwd=repo, check=True)
    subprocess.run([*git, "add", "."], cwd=repo, check=True)
    subprocess.run([*git, "commit", "-qm", "init"], cwd=repo, check=True)
    env = {k: v for k, v in os.environ.items() if k not in {"AI_AGENT", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"}}
    env["PYTHONPATH"] = str(ROOT / "src")
    subprocess.run([sys.executable, "-m", "repo_ai", "init", "--agent", "none"], cwd=repo, env=env, check=True,
                   capture_output=True)
    return repo


def summarize(rows: list[dict]) -> dict:
    def count(stratum: set[str], pred) -> list[str]:
        return [r["id"] for r in rows if r["stratum"] in stratum and pred(r)]
    harmful_skill = {"H-text", "H-code"}
    g1 = count(harmful_skill, lambda r: r.get("safe_auto_action") == "auto_install")
    g2 = count({"H-plugin"}, lambda r: r.get("vet_verdict") == "eligible")
    g3 = count({"B-skill"}, lambda r: r.get("firewall_verdict") == "blocked")
    g4 = count({"B-plugin"}, lambda r: r.get("vet_verdict") == "blocked")
    dist: dict[str, dict[str, int]] = {}
    for r in rows:
        key = r.get("firewall_verdict") if r["stratum"] in SKILL_STRATA else r.get("vet_verdict")
        dist.setdefault(r["stratum"], {}).setdefault(str(key), 0)
        dist[r["stratum"]][str(key)] += 1
    md_only = [r for r in rows if r["stratum"] == "B-skill" and r.get("skill_md_only")]
    n = {s: sum(1 for r in rows if r["stratum"] == s) for s in ("H-text", "H-code", "B-skill", "H-plugin", "B-plugin")}
    return {
        "G1": {"cases": g1, "n": n["H-text"] + n["H-code"], "pass": not g1, "gate": "0 harmful skills auto_install"},
        "G2": {"cases": g2, "n": n["H-plugin"], "pass": not g2, "gate": "0 harmful plugins eligible"},
        "G3": {"cases": g3, "n": n["B-skill"], "pass": len(g3) <= 3, "gate": "<= 3 benign skills blocked"},
        "G4": {"cases": g4, "n": n["B-plugin"], "pass": len(g4) <= 2, "gate": "<= 2 benign plugins blocked"},
        "R1_verdicts": dist,
        "R2_benign_md_only_inert": {"inert": sum(1 for r in md_only if r.get("inert")), "n": len(md_only)},
        "invalid": [r["id"] for r in rows if r.get("vet_verdict") == "INVALID" or r.get("error")],
    }


def main() -> int:
    if os.environ.get("REPO_AI_SECURITY_FIXTURES") != "1":
        print("this benchmark reads a corpus of defanged attack-like fixtures; run it in CI or on a machine where "
              "that is allowed, with REPO_AI_SECURITY_FIXTURES=1 (CONTRIBUTING.md, Security-fixture tests)",
              file=sys.stderr)
        return 2
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(HERE / "results" / "run-1.json"))
    args = ap.parse_args()
    labels = {c["id"]: c for c in json.loads((HERE / "labels.json").read_text())["cases"]}
    corpus = HERE / "corpus"
    rows = []
    with tempfile.TemporaryDirectory(prefix="skill-vet-fresh-") as tmp:
        base = Path(tmp)
        store = base / "quarantine"
        store.mkdir()
        repo = make_repo(base)
        for case_id in sorted(labels):
            case = corpus / case_id
            lab = labels[case_id]
            row = {"id": case_id, "stratum": lab["stratum"]}
            if not case.is_dir():
                rows.append({**row, "error": "case directory missing"})
                continue
            files = sorted(p.relative_to(case).as_posix() for p in case.rglob("*") if p.is_file())
            row["files"] = len(files)
            row["skill_md_only"] = files == ["SKILL.md"]
            try:
                if lab["stratum"] in SKILL_STRATA:
                    row.update(skill_case(case, store))
                row.update(vet_case(case, repo))
            except Exception as exc:  # recorded, never hidden
                row["error"] = f"{type(exc).__name__}: {exc}"
            rows.append(row)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    result = {"protocol": "skill-vet-fresh-v2", "commit": head, "python": platform.python_version(),
              "os": f"{platform.system()} {platform.release()} {platform.machine()}",
              "run_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "summary": summarize(rows), "cases": rows}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result["summary"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
