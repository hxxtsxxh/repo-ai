"""c11-attribution-v1 harness (PROTOCOL.md). $0: no model call. Host: git, the podman CLI and the repo-ai executable
only; project code runs only in podman containers (repo-ai's podman backend, and journey-live-v1's native check).

    python run.py prep    --work DIR                  # frozen tests + upstream ref, existing images, native check
    python run.py run     --work DIR --repo-ai PATH   # replay mission with a frozen declaration, then coverage
    python run.py state   --work DIR                  # amendment 1: re-read the recorded missions' state files
    python run.py export  --work DIR --out FILE       # records with paths shortened -> results/run-1.jsonl
    python run.py package --work DIR --records FILE   # the reviewer's tables (markdown on stdout)

Reuses journey-live-v1's pinned defects, tasks and helpers (imported from ../journey-live-v1/run.py). Unlike its
prep, this one never pulls or builds an image: it uses the existing `localhost/journey-<defect>-deps:1` images.
Every step is appended to DIR/records.jsonl.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("journey_live_v1", HERE.parent / "journey-live-v1" / "run.py")
J = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(J)  # type: ignore[union-attr]

DEFECTS = J.DEFECTS
ORDER = ["humanize", "more-itertools", "pyjwt", "marshmallow"]  # marshmallow optional, last
REQ_DIR = HERE / "requirements"
BUILD = "repo-ai 0.12.8"
STUB = '__version__ = version = "0.0.0"\n__version_tuple__ = version_tuple = (0, 0, 0)\n'


def tag_of(name: str) -> str:
    return f"localhost/journey-{name}-deps:1"


def declared_tests(name: str) -> list[str]:
    decl = json.loads((REQ_DIR / f"{name}.json").read_text())
    return sorted({t for r in decl["requirements"] for t in r["tests"]})


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prep(work: Path, names: list[str], log) -> None:
    for name in names:
        d = DEFECTS[name]
        repo = work / name / "repo"
        if not repo.exists():
            J.sh([*J.GIT, "clone", "-q", "--no-checkout", f"https://github.com/{d['slug']}.git", str(repo)], check=True)
        J.sh([*J.GIT, "checkout", "-q", "-B", "journey", d["base"]], repo, check=True)
        files = J.changed(repo, d["base"], d["fix"])
        tests = [f for f in files if J.TEST_PATH.search(f)]
        sources = [f for f in files if f not in tests]
        J.sh([*J.GIT, "checkout", "-q", d["fix"], "--", *tests], repo, check=True)
        J.sh([*J.GIT, "commit", "-qm", "frozen tests (upstream fix's test changes only)"], repo, check=True)
        frozen = J.sh([*J.GIT, "rev-parse", "HEAD"], repo, check=True).stdout.decode().strip()
        J.sh([*J.GIT, "checkout", "-q", d["fix"], "--", *sources], repo, check=True)
        J.sh([*J.GIT, "commit", "-qm", "upstream fix (reference)"], repo, check=True)
        upstream = J.sh([*J.GIT, "rev-parse", "HEAD"], repo, check=True).stdout.decode().strip()
        J.sh([*J.GIT, "update-ref", "refs/journey/upstream", upstream], repo, check=True)
        J.sh([*J.GIT, "reset", "-q", "--hard", frozen], repo, check=True)
        log(name, "frozen-tests", base=d["base"], fix=d["fix"], frozen=frozen, upstream_ref=upstream,
            test_files=tests, source_files=sources)
        tag = tag_of(name)
        insp = J.sh(["podman", "image", "inspect", "--format", "{{.Digest}} {{.Id}}", tag])
        if insp.returncode != 0:  # never built here: the protocol uses the existing images only
            log(name, "image", ok=False, tag=tag, why="image not present locally (not built by this study)")
            continue
        digest, image_id = insp.stdout.decode().split()
        installed = J.sh(["podman", "run", "--rm", "--network=none", tag, "pip", "show", d["dist"]])
        log(name, "image", ok=True, tag=tag, digest=digest, image_id=image_id,
            project_installed=installed.returncode == 0)
        with tempfile.TemporaryDirectory(prefix="c11-native-", dir=work) as tmp:
            t = Path(tmp)
            base_run = J.podman_test(tag, J.export(repo, frozen, t / "frozen"), [], version_file=d.get("version_file"))
            fix_run = J.podman_test(tag, J.export(repo, upstream, t / "fix"), [], version_file=d.get("version_file"))
        newly = sorted(set(base_run["failed"]) - set(fix_run["failed"]))
        wanted = declared_tests(name)
        log(name, "native-check", qualifies=base_run["exit"] != 0 and bool(newly), frozen_failed=base_run["failed"],
            fix_failed=fix_run["failed"], fixed_by_upstream=newly, base_exit=base_run["exit"], fix_exit=fix_run["exit"],
            expect_fix=newly if fix_run["failed"] else [], collected_frozen=len(base_run["outcomes"]),
            collected_fix=len(fix_run["outcomes"]),
            declared_outcomes={t: [base_run["outcomes"].get(t), fix_run["outcomes"].get(t)] for t in wanted},
            declared_not_collected=[t for t in wanted if t not in fix_run["outcomes"]],
            base_tail=base_run["tail"][-600:], fix_tail=fix_run["tail"][-600:])


def workspaces() -> set[str]:
    return set(J.leftover_workspaces())


def mission_state(checkout: Path, mid: str) -> dict:
    """The mission record from repo-ai's store (`{"record": ..., "schema", "sha256"}` on disk; amendment 1)."""
    found = [p for p in (checkout / ".repo-ai").rglob(f"missions/{mid}.json")] if mid else []
    raw = json.loads(found[0].read_text()) if found else {}
    return raw.get("record") if isinstance(raw.get("record"), dict) else raw


def state(work: Path, names: list[str], log) -> None:
    """Amendment 1: read each recorded mission's state file again (nothing is run) for the change-exercise record
    and executors, which run-1's `mission` rows missed (the reader did not unwrap the store's `record`)."""
    for name in names:
        rows = [r for r in J.rows(work) if r["defect"] == name and r["step"] == "mission" and r.get("mission_id")]
        if not rows:
            continue
        mid = rows[-1]["mission_id"]
        st = mission_state(work / name / "mission", mid)
        log(name, "mission-state", mission_id=mid, found=bool(st), exercise=st.get("exercise"),
            candidate_executor=(st.get("candidate") or {}).get("executor"),
            baseline_executor=(st.get("baseline") or {}).get("executor"))


SUMMARY_KEYS = ("id", "state", "verdict", "effective_verdict", "standing", "freshness", "freshness_reasons", "reasons",
                "recovery", "diff")


def run(work: Path, names: list[str], exe: str, log) -> None:
    version = J.checked_build(exe, log)
    if version != BUILD or "--requirements" not in J.sh([exe, "do", "--help"]).stdout.decode():
        raise SystemExit(f"{version}: the protocol needs {BUILD} with `do --requirements`; nothing was run")
    for name in names:
        d = DEFECTS[name]
        check, image = J.last(work, name, "native-check"), J.last(work, name, "image")
        frozen = J.last(work, name, "frozen-tests")
        if not check["qualifies"] or not image.get("ok") or image.get("project_installed"):
            log(name, "skipped", why="did not qualify natively, or the image is missing or holds the project")
            continue
        req = REQ_DIR / f"{name}.json"
        ckout = work / name / "mission"
        shutil.rmtree(ckout, ignore_errors=True)
        J.sh([*J.GIT, "clone", "-q", "--no-hardlinks", str(work / name / "repo"), str(ckout), "-b", "journey"],
             check=True)
        J.sh([*J.GIT, "fetch", "-q", str(work / name / "repo"), frozen["upstream_ref"]], ckout, check=True)
        if d.get("version_file"):  # hatch-vcs generates it at build time; the clone has none (gitignored)
            (ckout / d["version_file"]).write_text(STUB)
        init = J.repo_ai(exe, ckout, "init", "--agent", "none")
        J.sh([*J.GIT, "add", "-A"], ckout, check=True)
        J.sh([*J.GIT, "commit", "-qm", "repo-ai init", "--allow-empty"], ckout, check=True)
        edits = []
        for target in d["write"]:
            before = J.sh([*J.GIT, "show", f"HEAD:{target}"], ckout, check=True).stdout
            after = J.sh([*J.GIT, "show", f"{frozen['upstream_ref']}:{target}"], ckout, check=True).stdout.decode()
            edits.append({"path": target, "before_sha256": hashlib.sha256(before).hexdigest(), "after": after})
        replay = work / name / "replay.json"  # outside the checkout: not part of the project tree
        replay.write_text(json.dumps({"schema": "repo-ai.replay/1", "label": "explicit simulated proposal: upstream "
                                      "fix (c11-attribution-v1, no model)", "edits": edits}))
        argv = ["do", d["task"], "--agent", "replay", "--replay", str(replay), "--run",
                *[a for w in d["write"] for a in ("--allow-write", w)], "--requirements", str(req),
                "--sandbox", "podman", "--image", image["tag"], "--json", "--max-seconds", "900"]
        for test in check.get("expect_fix") or []:
            argv += ["--expect-fix", test]
        ws_before = workspaces()
        log(name, "mission-start", build=version, requirements_sha256=sha256(req), init_exit=init["exit"],
            image=image["tag"], image_digest=image["digest"], workspaces_before=len(ws_before))
        mission = J.repo_ai(exe, ckout, *argv, timeout=2400)
        rec = mission.pop("record") or {}
        mid = rec.get("id")
        summary = {k: rec.get(k) for k in SUMMARY_KEYS if k in rec}
        summary["passport_verdict"] = (rec.get("passport") or {}).get("verdict")
        summary["observed_verdict"] = J.observed_verdict(rec)
        state = mission_state(ckout, mid) if mid else {}
        cov = J.repo_ai(exe, ckout, "coverage", mid, "--json") if mid else None
        cov_text = J.sh([exe, "coverage", mid], ckout).stdout.decode() if mid else None
        ws_after = workspaces()
        log(name, "mission", **mission, mission=summary, mission_id=mid,
            exercise=state.get("exercise"), candidate_executor=(state.get("candidate") or {}).get("executor"),
            baseline_executor=(state.get("baseline") or {}).get("executor"),
            coverage=(cov or {}).get("record"), coverage_exit=(cov or {}).get("exit"),
            coverage_stderr=(cov or {}).get("stderr"), coverage_text=cov_text,
            workspaces_left_by_run=sorted(ws_after - ws_before))


ROOTS = [(str(Path.home()), "~")]


def shorten(obj, subs: list[tuple[str, str]]):
    if isinstance(obj, str):
        for a, b in subs:
            obj = obj.replace(a, b)
        return obj
    if isinstance(obj, list):
        return [shorten(x, subs) for x in obj]
    if isinstance(obj, dict):
        return {shorten(k, subs): shorten(v, subs) for k, v in obj.items()}
    return obj


def export(work: Path, out: Path, exe: str | None) -> None:
    subs = [(str(work.resolve()), "<work>"), (str(work), "<work>"), (str(HERE.parent.parent), "<repo>")]
    if exe:
        subs.append((str(Path(exe).resolve().parent.parent), "<venv>"))
        subs.append((str(Path(exe).parent.parent), "<venv>"))
    tmp = tempfile.gettempdir()
    subs += [(os.path.realpath(tmp), "<tmp>"), (tmp, "<tmp>"), ("/private/var/folders", "<tmp>"),
             ("/var/folders", "<tmp>"), *ROOTS]
    with out.open("w", encoding="utf-8") as f:
        for row in J.rows(work):
            f.write(json.dumps(shorten(row, subs), sort_keys=True) + "\n")


# ---- reviewer package -------------------------------------------------------------------------------------------

_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$")


def numbered_diff(repo: Path, a: str, b: str, paths: list[str]) -> str:
    """The unified diff with old/new line numbers in front of every line (`-` old only, `+` new only)."""
    raw = J.sh([*J.GIT, "diff", "-U3", a, b, "--", *paths], repo, check=True).stdout.decode()
    out, old, new = [], 0, 0
    for line in raw.split("\n"):
        m = _HUNK.match(line)
        if m:
            old, new = int(m.group(1)), int(m.group(2))
            out.append(line)
        elif line.startswith(("diff --git", "index ", "--- ", "+++ ")):
            out.append(line)
        elif line.startswith("+"):
            out.append(f"{'':>5} {new:>5} {line}")
            new += 1
        elif line.startswith("-"):
            out.append(f"{old:>5} {'':>5} {line}")
            old += 1
        elif line.startswith(" "):
            out.append(f"{old:>5} {new:>5} {line}")
            old, new = old + 1, new + 1
    return "\n".join(out).rstrip()


def test_source(repo: Path, rev: str, test_id: str) -> str:
    """The source of one declared test function at `rev` (with its line numbers), found by name in its file."""
    file, _, rest = test_id.partition("::")
    parts = rest.split("::")
    func = re.sub(r"\[.*$", "", parts[-1])
    text = J.sh([*J.GIT, "show", f"{rev}:{file}"], repo, check=True).stdout.decode().split("\n")
    after = 0
    for cls in parts[:-1]:  # a method: search after its class statement only
        after = next((i for i, l in enumerate(text) if i >= after and re.match(rf"\s*class {re.escape(cls)}\b", l)),
                     len(text))
    start = next((i for i, l in enumerate(text) if i >= after and re.match(rf"\s*def {re.escape(func)}\(", l)), None)
    if start is None:
        return f"(def {func} not found in {file})"
    while start > 0 and text[start - 1].strip().startswith("@"):
        start -= 1
    indent = len(text[start]) - len(text[start].lstrip())
    end = start + 1
    while end < len(text) and (not text[end].strip() or len(text[end]) - len(text[end].lstrip()) > indent):
        end += 1
    while end > start and not text[end - 1].strip():
        end -= 1
    return "\n".join(f"{i + 1:>5}  {text[i]}" for i in range(start, end))


def package(work: Path, records: Path) -> None:
    rows = [json.loads(l) for l in records.read_text().splitlines()]
    for name in ORDER:
        mine = [r for r in rows if r["defect"] == name]
        if not mine:
            continue
        frozen = [r for r in mine if r["step"] == "frozen-tests"][-1]
        mission = ([r for r in mine if r["step"] == "mission"] or [None])[-1]
        repo = work / name / "repo"
        print(f"\n## {name}\n")
        print("```diff")
        print(numbered_diff(repo, frozen["frozen"], frozen["upstream_ref"],
                            [f for f in frozen["source_files"] if f.endswith(".py")]))
        print("```\n")
        decl = json.loads((REQ_DIR / f"{name}.json").read_text())
        for i, r in enumerate(decl["requirements"], 1):
            print(f"- **R{i}** ({r['kind']}): {r['text']}")
            for t in r["tests"]:
                print(f"  - `{t}`")
        print()
        shown: dict[str, list[str]] = {}
        for t in declared_tests(name):  # one listing per test function (parametrized cases share one)
            shown.setdefault(test_source(repo, frozen["frozen"], t), []).append(t)
        for src, ids in shown.items():
            print(", ".join(f"`{t}`" for t in ids) + f" at the frozen commit:\n\n```python\n{src}\n```\n")
        if not mission:
            print("(no mission record)\n")
            continue
        st = ([r for r in mine if r["step"] == "mission-state"] or [{}])[-1]
        ex = st.get("exercise") or mission.get("exercise") or {}
        per_test = ex.get("per_test") if isinstance(ex.get("per_test"), dict) else {}
        decl_ids = set(declared_tests(name))  # declared as pytest node ids, the per-test record's keys
        lines = sorted({l for v in per_test.values() for l in v} | set(ex.get("unexercised") or [])
                       | set(ex.get("changed_outside_tests") or []), key=lambda s: (s.rsplit(":", 1)[0],
                                                                                   int(s.rsplit(":", 1)[1])))
        print("| changed line | declared tests that ran it | other tests that ran it | outside any test |")
        print("|---|---|---|---|")
        for line in lines:
            runners = sorted(t for t, v in per_test.items() if line in v)
            dec = [t for t in runners if t in decl_ids]
            others = len(runners) - len(dec)
            outside = "yes" if line in (ex.get("changed_outside_tests") or []) else ""
            unexercised = " (never run: unexercised)" if line in (ex.get("unexercised") or []) else ""
            print(f"| `{line}`{unexercised} | {', '.join('`' + t + '`' for t in dec) or '—'} "
                  f"| {others} | {outside} |")
        print()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["prep", "run", "state", "export", "package"])
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--repo-ai", dest="exe")
    ap.add_argument("--only", action="append")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--records", type=Path)
    args = ap.parse_args()
    if Path.home().resolve() not in args.work.resolve().parents:
        raise SystemExit("--work must be under HOME")
    args.work.mkdir(parents=True, exist_ok=True)
    log = J.Log(args.work)
    names = args.only or ORDER
    if args.stage == "prep":
        prep(args.work, names, log)
    elif args.stage == "run":
        if not args.exe:
            raise SystemExit("--repo-ai PATH is required")
        run(args.work, names, args.exe, log)
    elif args.stage == "state":
        state(args.work, names, log)
    elif args.stage == "export":
        export(args.work, args.out, args.exe)
    else:
        package(args.work, args.records)
    return 0


if __name__ == "__main__":
    sys.exit(main())
