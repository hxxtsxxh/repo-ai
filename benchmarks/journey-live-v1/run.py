"""journey-live-v1 harness (PREREGISTRATION.md). Host: git, podman CLI and the repo-ai executable only; project code
runs only in podman containers. Stages:

    python run.py prep     --work DIR                   # clones, frozen tests, images, native checks (no model)
    python run.py control  --work DIR --repo-ai PATH    # positive control: upstream fix as a replay (no model)
    python run.py run      --work DIR --repo-ai PATH    # onboarding, live missions, L1, oracle, apply/undo
    python run.py recovery --work DIR --repo-ai PATH    # failure recovery (no model), after every live mission

DIR must be one the provider sandbox cannot read (under HOME on macOS): the clones hold upstream history and the
records. Sessions are counted from DIR/records.jsonl (`live-mission-start`), so a rerun never repeats one.

Every step is appended to DIR/records.jsonl; nothing is retried after a model call.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DEFECTS = {
    "humanize": {
        "slug": "python-humanize/humanize", "base": "8059ebe1732c89177709476165f6e87cc76fe1b7",
        "fix": "2968d44280a68f775db73ddeb2f2fc6c05edac84", "release": "2968d44280a68f775db73ddeb2f2fc6c05edac84",
        "dist": "humanize", "extras": "tests", "write": ["src/humanize/filesize.py"],
        "version_file": "src/humanize/_version.py",
        "task": "`humanize.naturalsize` no longer accepts a float such as `1.0` or a numeric string such as `\"1\"`; "
                "both should give `\"1 Byte\"`, as an int does. Fix it in src/humanize/filesize.py without changing "
                "the tests.",
    },
    "marshmallow": {
        "slug": "marshmallow-code/marshmallow", "base": "c7152171fbe7c12f5ac77800a43dc7ad8ae2e2cf",
        "fix": "de5e842aeaf7eacfa42e9231f8b18e0792851c45", "release": "84b15960272c16525c945ae99749e505310612a9",
        "dist": "marshmallow", "extras": "tests", "write": ["src/marshmallow/schema.py", "src/marshmallow/utils.py"],
        "task": "A Schema subclass that declares a field as a class (`name = fields.String`) instead of an instance "
                "must raise `TypeError('Field for \"name\" must be declared as a Field instance')` when the class is "
                "defined, not later when it is used. Fix it in src/marshmallow/ without changing the tests.",
    },
    "more-itertools": {
        "slug": "more-itertools/more-itertools", "base": "c8baa10e66de18662114b71edcfa32f5dfdd2881",
        "fix": "719a333bccd20ced15a7b4688fb6d47f05d8606d", "release": "5c1fb20d4b918a5e4b38898dac983d85f6952f03",
        "dist": "more-itertools", "extras": "", "write": ["more_itertools/more.py"],
        "task": "`unique_in_window(iterable, n)` gives wrong results: `list(unique_in_window([1, 2, 3, 4, 4, 4], 1))` "
                "should be `[1, 2, 3, 4, 4, 4]`, and `list(unique_in_window([0, 1, 1, 1, 1, 1, 1, 1, 1, 0, 2, 3, 4, "
                "2], 2))` should be `[0, 1, 0, 2, 3, 4, 2]`. Fix it in more_itertools/more.py without changing the "
                "tests.",
    },
    "pyjwt": {
        "slug": "jpadilla/pyjwt", "base": "783f324e5d2155462515ced45718fc164dd04db2",
        "fix": "33022c25525c1020869c71ce2a4109e44ae4ced1", "release": "3ebbb22f30f2b1b41727b269a08b427e9a85d6bb",
        "dist": "PyJWT", "extras": "tests,crypto", "write": ["jwt/api_jwt.py"],
        "task": "`jwt.decode(token, key, issuer=\"urn:expected\", algorithms=[\"HS256\"])` accepts a token whose "
                "`iss` is `\"urn:\"` (a partial match). It must raise `InvalidIssuerError` unless `iss` equals the "
                "issuer (or one of them, when a list is given). Fix it in jwt/api_jwt.py without changing the tests.",
    },
}
BASE_IMAGE = "docker.io/library/python:3.12-slim"
MAX_COST = "1.00"
GIT = ["git", "-c", "core.hooksPath=/dev/null", "-c", "user.name=journey", "-c", "user.email=journey@example.invalid",
       "-c", "commit.gpgsign=false"]
TEST_PATH = re.compile(r"(^|/)(tests?|testing)/|(^|/)test_[^/]*\.py$|_test\.py$|(^|/)conftest\.py$")


def sh(argv: list[str], cwd: Path | None = None, *, timeout: float = 1800, env: dict | None = None,
       check: bool = False, stdin: bytes | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(argv, cwd=cwd, capture_output=True, timeout=timeout, env=env, input=stdin, check=False)
    if check and proc.returncode != 0:
        raise RuntimeError(f"{argv[:4]} exited {proc.returncode}: {proc.stderr.decode(errors='replace')[-800:]}")
    return proc


def text(b: bytes, limit: int = 6000) -> str:
    s = b.decode("utf-8", "replace")
    return s if len(s) <= limit else s[:limit // 2] + "\n…\n" + s[-limit // 2:]


class Log:
    def __init__(self, work: Path) -> None:
        self.path = work / "records.jsonl"

    def __call__(self, defect: str, step: str, **data) -> dict:
        row = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "defect": defect, "step": step, **data}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
        print(f"[{defect}] {step}: " + json.dumps({k: v for k, v in data.items() if k not in ("stdout", "stderr",
                                                                                          "record")})[:300])
        return row


def changed(repo: Path, a: str, b: str) -> list[str]:
    out = sh([*GIT, "diff", "--name-only", "-z", a, b], repo, check=True).stdout
    return [p.decode() for p in out.split(b"\0") if p]


def export(repo: Path, rev: str, dest: Path) -> Path:
    """The tree of `rev` as plain files (no .git), for native container runs."""
    dest.mkdir(parents=True)
    archive = sh([*GIT, "archive", "--format=tar", rev], repo, check=True).stdout
    sh(["tar", "-x", "-C", str(dest)], stdin=archive, check=True)
    return dest


def podman_test(image: str, tree: Path, args: list[str], *, version_file: str | None = None) -> dict:
    """The project's own pytest, natively, in the container: no network, read-only root, no capabilities."""
    if version_file:  # what hatch-vcs would generate at build time (a git archive has none)
        (tree / version_file).write_text('__version__ = version = "0.0.0"\n__version_tuple__ = version_tuple = (0, 0, 0)\n')
    env = ["-e", "HOME=/tmp", "-e", "PYTHONDONTWRITEBYTECODE=1"]
    if (tree / "src").is_dir():
        env += ["-e", "PYTHONPATH=/work/src"]
    proc = sh(["podman", "run", "--rm", "--network=none", "--read-only", "--tmpfs", "/tmp", "--cap-drop=all",
               "--security-opt", "no-new-privileges", "--pids-limit", "512", "--memory", "2g",
               "-v", f"{tree}:/work:rw", "-w", "/work", *env, image,
               "python", "-m", "pytest", "-q", "-rA", "--color=no", "-p", "no:cacheprovider", *args], timeout=900)
    out = re.sub(r"\x1b\[[0-9;]*m", "", proc.stdout.decode("utf-8", "replace"))  # a project may force colour
    outcomes = {}
    subfailed = set()
    for line in out.splitlines():
        if line.startswith("SUBFAILED"):  # pytest 9 subtests: "SUBFAILED(<params>) <node id>"; the test failed
            m = re.search(r"(\S+\.py::.+?)(?: - .*)?$", line)
            if m:
                subfailed.add(m.group(1))
            continue
        # node ids may contain spaces (parametrize ids); a failure line ends with " - <message>"
        m = re.match(r"^(PASSED|FAILED|ERROR|XFAIL|XPASS) (.+?)(?: - .*)?$", line)
        if m and "::" in m.group(2):
            outcomes[m.group(2)] = m.group(1)
    for node in subfailed:
        outcomes[node] = "FAILED"
    errors = sorted({m.group(1) for m in re.finditer(r"^ERROR (\S+\.py)(?: - .*)?$", out, re.M)})
    return {"exit": proc.returncode, "outcomes": outcomes, "collection_errors": errors, "failed": sorted(t for t, o in outcomes.items()
                                                                          if o in ("FAILED", "ERROR")),
            "tail": text(proc.stdout, 1500)}


def prep(work: Path, names: list[str], log: Log) -> None:
    sh(["podman", "pull", "-q", BASE_IMAGE], check=True, timeout=900)
    digest = sh(["podman", "image", "inspect", "--format", "{{.Digest}}", BASE_IMAGE], check=True).stdout.decode().strip()
    pinned = f"{BASE_IMAGE}@{digest}"
    log("all", "base-image", image=pinned)
    for name in names:
        d = DEFECTS[name]
        repo = work / name / "repo"
        if not repo.exists():
            sh([*GIT, "clone", "-q", "--no-checkout", f"https://github.com/{d['slug']}.git", str(repo)], check=True)
        sh([*GIT, "checkout", "-q", "-B", "journey", d["base"]], repo, check=True)
        files = changed(repo, d["base"], d["fix"])
        tests = [f for f in files if TEST_PATH.search(f)]
        sh([*GIT, "checkout", "-q", d["fix"], "--", *tests], repo, check=True)
        sh([*GIT, "commit", "-qm", "frozen tests (upstream fix's test changes only)"], repo, check=True)
        frozen = sh([*GIT, "rev-parse", "HEAD"], repo, check=True).stdout.decode().strip()
        log(name, "frozen-tests", base=d["base"], fix=d["fix"], frozen=frozen, test_files=tests,
            source_files=[f for f in files if f not in tests])
        # dependencies-only image: install the base with its test extras, then uninstall the project itself
        ctx = work / name / "image"
        shutil.rmtree(ctx, ignore_errors=True)
        export(repo, d["base"], ctx / "project")
        extras = f"[{d['extras']}]" if d["extras"] else ""
        (ctx / "Containerfile").write_text(
            f"FROM {pinned}\nCOPY project /tmp/project\n"
            "ENV SETUPTOOLS_SCM_PRETEND_VERSION=0.0.0 PIP_DISABLE_PIP_VERSION_CHECK=1\n"
            f'RUN pip install --no-cache-dir "/tmp/project{extras}" pytest && pip uninstall -y {d["dist"]} '
            "&& rm -rf /tmp/project && pip freeze > /deps-freeze.txt\n")
        tag = f"localhost/journey-{name}-deps:1"
        build = sh(["podman", "build", "-q", "-t", tag, "-f", str(ctx / "Containerfile"), str(ctx)], timeout=1800)
        if build.returncode != 0:
            log(name, "image", ok=False, stderr=text(build.stderr))
            continue
        img_digest = sh(["podman", "image", "inspect", "--format", "{{.Digest}}", tag], check=True).stdout.decode().strip()
        freeze = sh(["podman", "run", "--rm", "--network=none", tag, "cat", "/deps-freeze.txt"], check=True).stdout
        installed = sh(["podman", "run", "--rm", "--network=none", tag, "pip", "show", d["dist"]])
        log(name, "image", ok=True, tag=tag, digest=img_digest, freeze=freeze.decode().split(),
            project_installed=installed.returncode == 0)
        # native checks: the frozen tests fail at the base and pass with the upstream fix
        with tempfile.TemporaryDirectory(prefix="journey-native-", dir=work) as tmp:
            t = Path(tmp)
            base_run = podman_test(tag, export(repo, frozen, t / "frozen"), [], version_file=d.get("version_file"))
            sh([*GIT, "checkout", "-q", d["fix"], "--", *[f for f in files if f not in tests]], repo, check=True)
            sh([*GIT, "commit", "-qm", "upstream fix (reference, not given to the agent)"], repo, check=True)
            upstream = sh([*GIT, "rev-parse", "HEAD"], repo, check=True).stdout.decode().strip()
            sh([*GIT, "update-ref", "refs/journey/upstream", upstream], repo, check=True)
            sh([*GIT, "reset", "-q", "--hard", frozen], repo, check=True)
            fix_run = podman_test(tag, export(repo, upstream, t / "fix"), [], version_file=d.get("version_file"))
        newly = sorted(set(base_run["failed"]) - set(fix_run["failed"]))
        qualifies = base_run["exit"] != 0 and bool(newly)
        log(name, "native-check", qualifies=qualifies, upstream_ref=upstream, frozen_failed=base_run["failed"],
            fix_failed=fix_run["failed"], fixed_by_upstream=newly, base_exit=base_run["exit"],
            fix_exit=fix_run["exit"], expect_fix=newly if fix_run["failed"] else [],
            base_tail=base_run["tail"], fix_tail=fix_run["tail"])


def last(work: Path, name: str, step: str) -> dict:
    rows = [json.loads(line) for line in (work / "records.jsonl").read_text().splitlines()]
    found = [r for r in rows if r["defect"] == name and r["step"] == step]
    if not found:
        raise SystemExit(f"{name}: no {step} record; run prep first")
    return found[-1]


STATE_DIR = ".repo-ai"  # repo-ai's own records (missions, receipts): written by apply and undo by design


def tree_state(repo: Path, *, state: bool = False) -> dict:
    """Every file under the checkout except .git, by sha256 and mode: tracked and untracked alike. repo-ai's state
    directory is reported separately (`state=True`), since apply and undo record themselves there."""
    out = {}
    for p in sorted(repo.rglob("*")):
        rel = p.relative_to(repo).as_posix()
        if rel == ".git" or rel.startswith(".git/") or not p.is_file() or p.is_symlink():
            continue
        if (rel == STATE_DIR or rel.startswith(STATE_DIR + "/")) != state:
            continue
        out[rel] = f"{hashlib.sha256(p.read_bytes()).hexdigest()} {oct(p.stat().st_mode & 0o777)}"
    return out


def repo_ai(exe: str, repo: Path, *args: str, timeout: float = 1800) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY",
                                                            "AI_AGENT", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
    try:
        proc = sh([exe, *args], repo, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as exc:  # recorded, never retried
        return {"argv": ["repo-ai", *args], "exit": None, "record": None, "timed_out": True,
                "stdout": text(exc.stdout or b""), "stderr": text(exc.stderr or b"", 3000)}
    try:
        record = json.loads(proc.stdout)
    except json.JSONDecodeError:
        record = None
    return {"argv": ["repo-ai", *args], "exit": proc.returncode, "record": record,
            "stdout": None if record is not None else text(proc.stdout), "stderr": text(proc.stderr, 3000)}


def rows(work: Path) -> list[dict]:
    path = work / "records.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def checked_build(exe: str, log: Log) -> str:
    """The repo-ai under test must have `do --sandbox/--image`; refuse before any session otherwise."""
    version = sh([exe, "--version"], check=True).stdout.decode().strip()
    shown = sh([exe, "do", "--help"]).stdout.decode()
    if "--sandbox" not in shown or "--image" not in shown:
        raise SystemExit(f"{version} has no `do --sandbox/--image`; nothing was run")
    log("all", "build", version=version)
    return version


def prepare_checkout(work: Path, name: str, d: dict, log: Log) -> Path:
    repo = work / name / "repo"
    sh([*GIT, "checkout", "-q", "journey"], repo, check=True)
    sh([*GIT, "clean", "-fdxq"], repo, check=True)
    if d.get("version_file"):  # hatch-vcs generates it at build time; the clone has none (it is gitignored)
        (repo / d["version_file"]).write_text('__version__ = version = "0.0.0"\n'
                                              '__version_tuple__ = version_tuple = (0, 0, 0)\n')
        log(name, "version-stub", path=d["version_file"],
            ignored=sh([*GIT, "check-ignore", "-q", d["version_file"]], repo).returncode == 0)
    return repo


def control(work: Path, names: list[str], exe: str, log: Log) -> None:
    """Positive control through repo-ai's own podman backend, no model: the upstream fix as an explicit replay
    proposal must PASS. Run in a separate clone (its replay never sits in the live checkout or its records)."""
    checked_build(exe, log)
    for name in names:
        d = DEFECTS[name]
        check, image = last(work, name, "native-check"), last(work, name, "image")
        ctl = work / name / "control"
        shutil.rmtree(ctl, ignore_errors=True)
        sh([*GIT, "clone", "-q", "--no-hardlinks", str(work / name / "repo"), str(ctl), "-b", "journey"], check=True)
        sh([*GIT, "fetch", "-q", str(work / name / "repo"), check["upstream_ref"]], ctl, check=True)
        if d.get("version_file"):
            (ctl / d["version_file"]).write_text('__version__ = version = "0.0.0"\n'
                                                 '__version_tuple__ = version_tuple = (0, 0, 0)\n')
        repo_ai(exe, ctl, "init", "--agent", "none")
        sh([*GIT, "add", "-A"], ctl, check=True)
        sh([*GIT, "commit", "-qm", "repo-ai init", "--allow-empty"], ctl, check=True)
        edits = []
        for target in d["write"]:
            before = sh([*GIT, "show", f"HEAD:{target}"], ctl, check=True).stdout
            after = sh([*GIT, "show", f"{check['upstream_ref']}:{target}"], ctl, check=True).stdout.decode()
            edits.append({"path": target, "before_sha256": hashlib.sha256(before).hexdigest(), "after": after})
        with tempfile.TemporaryDirectory(prefix="journey-control-") as tmp:
            replay = Path(tmp) / "replay.json"
            replay.write_text(json.dumps({"schema": "repo-ai.replay/1", "label": "explicit simulated proposal: "
                                          "upstream fix (positive control)", "edits": edits}))
            argv = ["do", d["task"], "--agent", "replay", "--replay", str(replay), "--run",
                    *[a for w in d["write"] for a in ("--allow-write", w)], "--sandbox", "podman", "--image",
                    image["tag"], "--json", "--max-seconds", "900"]
            for test in check.get("expect_fix") or []:
                argv += ["--expect-fix", test]
            res = repo_ai(exe, ctl, *argv, timeout=2400)
        rec = res["record"] or {}
        verdict = rec.get("effective_verdict", rec.get("verdict"))
        log(name, "control", **res, verdict=verdict, ok=verdict in ("PASS", "PASS_WITH_PRE_EXISTING_FAILURES"))
        shutil.rmtree(ctl, ignore_errors=True)


def run(work: Path, names: list[str], exe: str, log: Log) -> None:
    version = checked_build(exe, log)
    for name in names:
        d = DEFECTS[name]
        history = rows(work)
        started = [r for r in history if r["step"] == "live-mission-start"]
        if any(r["defect"] == name for r in started):
            log(name, "skipped", why="a live session was already started for this defect (never repeated)")
            continue
        if len(started) >= 4:
            log(name, "skipped", why="the 4 approved Claude sessions are used")
            continue
        check, image = last(work, name, "native-check"), last(work, name, "image")
        controls = [r for r in history if r["defect"] == name and r["step"] == "control"]
        if not check["qualifies"] or not image.get("ok") or image.get("project_installed") or \
                not (controls and controls[-1].get("ok")):
            log(name, "skipped", why="did not qualify, or the positive control did not pass (no model call)")
            continue
        repo = prepare_checkout(work, name, d, log)
        tag = image["tag"]
        sb = ["--sandbox", "podman", "--image", tag]
        init = repo_ai(exe, repo, "init", "--agent", "none")
        sh([*GIT, "add", "-A"], repo, check=True)
        sh([*GIT, "commit", "-qm", "repo-ai init", "--allow-empty"], repo, check=True)
        log(name, "onboarding-init", **init)
        log(name, "onboarding-verify", **repo_ai(exe, repo, "verify", "--run", "--base", d["base"], *sb, "--json"))
        argv = ["do", d["task"], "--agent", "claude", "--allow-live-provider", "--max-cost-usd", MAX_COST, "--run",
                *[a for w in d["write"] for a in ("--allow-write", w)], *sb, "--json", "--max-seconds", "900"]
        for test in check.get("expect_fix") or []:
            argv += ["--expect-fix", test]
        log(name, "live-mission-start", build=version, session_number=len(started) + 1)
        mission = repo_ai(exe, repo, *argv, timeout=2400)
        rec = mission["record"] or {}
        prov = rec.get("provider") or {}
        log(name, "live-mission", **mission, cost_usd=prov.get("cost_usd"), cost_status=prov.get("cost_status"))
        mid, verdict = rec.get("id"), rec.get("effective_verdict", rec.get("verdict"))
        diff = rec.get("diff") or ""
        if mid and diff:
            oracle(work, name, d, repo, check, diff, tag, verdict, log)
        if mid and verdict in ("PASS", "PASS_WITH_PRE_EXISTING_FAILURES"):
            before, state_before = tree_state(repo), tree_state(repo, state=True)
            applied = repo_ai(exe, repo, "apply", mid, "--json")
            after_apply = tree_state(repo)
            undone = repo_ai(exe, repo, "undo", mid, "--json")
            after_undo, state_after = tree_state(repo), tree_state(repo, state=True)
            ok = applied["exit"] == 0 and bool((applied["record"] or {}).get("applied_to_source"))
            log(name, "apply-undo", apply=applied, undo=undone, apply_ok=ok,
                applied_changed=sorted(k for k in set(before) | set(after_apply) if before.get(k) != after_apply.get(k)),
                undo_identical=after_undo == before if ok else None,
                undo_differences=sorted(k for k in set(before) | set(after_undo) if before.get(k) != after_undo.get(k)),
                state_files_changed=sorted(k for k in set(state_before) | set(state_after)
                                           if state_before.get(k) != state_after.get(k)))
    spent = [r for r in rows(work) if r["step"] == "live-mission"]
    log("all", "sessions", started=len([r for r in rows(work) if r["step"] == "live-mission-start"]),
        reported_cost_usd=round(sum(float(r.get("cost_usd") or 0) for r in spent), 4),
        cost_statuses=sorted({str(r.get("cost_status")) for r in spent}))


def oracle(work: Path, name: str, d: dict, repo: Path, check: dict, diff: str, tag: str, verdict: str | None,
           log: Log) -> None:
    """L1: the candidate on the frozen tests, natively in the container. Then the hidden upstream-differential
    oracle: the fix's test files as of the release, on base+upstream and on base+candidate."""
    tests = last(work, name, "frozen-tests")["test_files"]
    with tempfile.TemporaryDirectory(prefix="journey-oracle-", dir=work) as tmp:
        t = Path(tmp)
        ref = export(repo, check["upstream_ref"], t / "upstream")
        cand = export(repo, "journey", t / "candidate")
        patch = t / "candidate.patch"
        patch.write_text(diff if diff.endswith("\n") else diff + "\n")
        applied = sh(["git", "apply", str(patch)], cand, stdin=b"")
        if applied.returncode != 0:
            log(name, "oracle", ok=False, why="candidate diff did not apply to an export", stderr=text(applied.stderr))
            return
        frozen = podman_test(tag, cand, [], version_file=d.get("version_file"))
        still = sorted(set(check["fixed_by_upstream"]) & set(frozen["failed"]))
        new = sorted(set(frozen["failed"]) - set(check["fix_failed"]))
        log(name, "native-frozen", candidate_exit=frozen["exit"], frozen_still_failing=still,
            new_failures_vs_upstream=new, l1_violation=verdict in ("PASS", "PASS_WITH_PRE_EXISTING_FAILURES")
            and bool(still or new), tail=frozen["tail"])
        missing = []
        for tree in (ref, cand):
            for f in tests:
                blob = sh([*GIT, "show", f"{d['release']}:{f}"], repo)
                if blob.returncode == 0:
                    (tree / f).parent.mkdir(parents=True, exist_ok=True)
                    (tree / f).write_bytes(blob.stdout)
                elif f not in missing:
                    missing.append(f)
        a = podman_test(tag, ref, tests, version_file=d.get("version_file"))
        b = podman_test(tag, cand, tests, version_file=d.get("version_file"))
    differ = sorted(k for k in a["outcomes"] if a["outcomes"][k] == "PASSED" and b["outcomes"].get(k) != "PASSED")
    log(name, "oracle", ok=True, release=d["release"], missing_at_release=missing, upstream_exit=a["exit"],
        candidate_exit=b["exit"], upstream_failed=a["failed"], candidate_failed=b["failed"],
        behavioural_differences=differ, compared=len(a["outcomes"]), upstream_tail=a["tail"][-600:],
        candidate_tail=b["tail"][-600:])


def recovery(work: Path, exe: str, log: Log) -> None:
    """Failure recovery without a model: a replay mission whose image has no pytest must not pass. Only after every
    live session, so the upstream fix it carries is never on disk while an agent runs."""
    started = {r["defect"] for r in rows(work) if r["step"] == "live-mission-start"}
    if not set(DEFECTS) <= started:
        raise SystemExit("recovery runs after the live missions: " + ", ".join(sorted(set(DEFECTS) - started)))
    checked_build(exe, log)
    name = "humanize"
    d = DEFECTS[name]
    pinned = last(work, "all", "base-image")["image"]
    sh(["podman", "tag", pinned, "localhost/journey-no-pytest:1"], check=True)
    repo = prepare_checkout(work, name, d, log)
    sh([*GIT, "reset", "-q", "--hard", "HEAD"], repo, check=True)
    upstream = last(work, name, "native-check")["upstream_ref"]
    target = d["write"][0]
    before = sh([*GIT, "show", f"HEAD:{target}"], repo, check=True).stdout
    after = sh([*GIT, "show", f"{upstream}:{target}"], repo, check=True).stdout.decode()
    with tempfile.TemporaryDirectory(prefix="journey-recovery-") as tmp:
        replay = Path(tmp) / "replay.json"
        replay.write_text(json.dumps({"schema": "repo-ai.replay/1", "label": "explicit simulated proposal: upstream "
                                      "fix", "edits": [{"path": target, "before_sha256": hashlib.sha256(before)
                                                        .hexdigest(), "after": after}]}))
        res = repo_ai(exe, repo, "do", d["task"], "--agent", "replay", "--replay", str(replay), "--run",
                      "--allow-write", target, "--sandbox", "podman", "--image", "localhost/journey-no-pytest:1",
                      "--json")
    rec = res["record"] or {}
    log(name, "failure-recovery", **res, verdict=rec.get("effective_verdict", rec.get("verdict")),
        reasons=rec.get("reasons"), recovery=rec.get("recovery"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["prep", "control", "run", "recovery"])
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--repo-ai", dest="exe")
    ap.add_argument("--only", action="append")
    args = ap.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    log = Log(args.work)
    names = args.only or list(DEFECTS)
    if args.stage == "prep":
        prep(args.work, names, log)
    else:
        if not args.exe:
            raise SystemExit("--repo-ai PATH is required")
        if args.stage == "control":
            control(args.work, names, args.exe, log)
        elif args.stage == "run":
            run(args.work, names, args.exe, log)
        else:
            recovery(args.work, args.exe, log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
