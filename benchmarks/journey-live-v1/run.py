"""journey-live-v1 harness (PREREGISTRATION.md). Host: git, podman CLI and the repo-ai executable only; project code
runs only in podman containers. Stages:

    python run.py prep  --work DIR                      # clones, frozen tests, images, native checks (no model)
    python run.py run   --work DIR --repo-ai PATH       # onboarding, live missions, oracle, apply/undo, recovery
    python run.py prep|run ... --only humanize           # one defect

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
    return {"exit": proc.returncode, "outcomes": outcomes, "failed": sorted(t for t, o in outcomes.items()
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


def tree_state(repo: Path) -> dict:
    """Every file under the checkout except .git, by sha256: tracked and untracked alike."""
    out = {}
    for p in sorted(repo.rglob("*")):
        rel = p.relative_to(repo).as_posix()
        if rel == ".git" or rel.startswith(".git/") or not p.is_file() or p.is_symlink():
            continue
        out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def repo_ai(exe: str, repo: Path, *args: str, timeout: float = 1800) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY",
                                                            "AI_AGENT", "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
    proc = sh([exe, *args], repo, timeout=timeout, env=env)
    try:
        record = json.loads(proc.stdout)
    except json.JSONDecodeError:
        record = None
    return {"argv": ["repo-ai", *args], "exit": proc.returncode, "record": record,
            "stdout": None if record is not None else text(proc.stdout), "stderr": text(proc.stderr, 3000)}


def run(work: Path, names: list[str], exe: str, log: Log, sessions_left: int) -> None:
    for name in names:
        d = DEFECTS[name]
        check = last(work, name, "native-check")
        image = last(work, name, "image")
        if not check["qualifies"] or not image.get("ok") or image.get("project_installed"):
            log(name, "skipped", why="did not qualify in prep (no model call)")
            continue
        repo = work / name / "repo"
        sh([*GIT, "checkout", "-q", "journey"], repo, check=True)
        sh([*GIT, "clean", "-fdxq"], repo, check=True)
        tag = image["tag"]
        sb = ["--sandbox", "podman", "--image", tag]
        init = repo_ai(exe, repo, "init", "--agent", "none")
        sh([*GIT, "add", "-A"], repo, check=True)
        sh([*GIT, "commit", "-qm", "repo-ai init", "--allow-empty"], repo, check=True)
        log(name, "onboarding-init", **init)
        log(name, "onboarding-verify", **repo_ai(exe, repo, "verify", "--run", *sb, "--json"))
        if sessions_left <= 0:
            log(name, "skipped", why="no Claude session left in the approved budget")
            continue
        argv = ["do", d["task"], "--agent", "claude", "--allow-live-provider", "--max-cost-usd", MAX_COST, "--run",
                *[a for w in d["write"] for a in ("--allow-write", w)], *sb, "--json", "--max-seconds", "900"]
        for test in check.get("expect_fix") or []:
            argv += ["--expect-fix", test]
        sessions_left -= 1
        mission = repo_ai(exe, repo, *argv, timeout=2400)
        log(name, "live-mission", **mission)
        rec = mission["record"] or {}
        mid, verdict = rec.get("id"), rec.get("effective_verdict", rec.get("verdict"))
        diff = rec.get("diff") or ""
        if mid and diff:
            oracle(work, name, d, repo, check, diff, tag, log)
        if mid and verdict in ("PASS", "PASS_WITH_PRE_EXISTING_FAILURES"):
            before = tree_state(repo)
            applied = repo_ai(exe, repo, "apply", mid, "--json")
            after_apply = tree_state(repo)
            undone = repo_ai(exe, repo, "undo", mid, "--json")
            after_undo = tree_state(repo)
            log(name, "apply-undo", apply=applied, undo=undone,
                applied_changed=sorted(k for k in set(before) | set(after_apply) if before.get(k) != after_apply.get(k)),
                undo_identical=after_undo == before,
                undo_differences=sorted(k for k in set(before) | set(after_undo) if before.get(k) != after_undo.get(k)))
    log("all", "sessions", left=sessions_left)


def oracle(work: Path, name: str, d: dict, repo: Path, check: dict, diff: str, tag: str, log: Log) -> None:
    """Hidden upstream-differential oracle: the fix's test files as of the release, on base+upstream and on
    base+candidate, natively in the container."""
    tests = last(work, name, "frozen-tests")["test_files"]
    with tempfile.TemporaryDirectory(prefix="journey-oracle-", dir=work) as tmp:
        t = Path(tmp)
        ref = export(repo, check["upstream_ref"], t / "upstream")
        cand = export(repo, "journey", t / "candidate")
        patch = t / "candidate.patch"
        patch.write_text(diff if diff.endswith("\n") else diff + "\n")
        applied = sh(["git", "apply", str(patch)], cand)
        if applied.returncode != 0:
            applied = sh(["patch", "-p1", "-i", str(patch)], cand)
        if applied.returncode != 0:
            log(name, "oracle", ok=False, why="candidate diff did not apply to an export", stderr=text(applied.stderr))
            return
        for tree in (ref, cand):
            for f in tests:
                blob = sh([*GIT, "show", f"{d['release']}:{f}"], repo)
                if blob.returncode == 0:
                    (tree / f).parent.mkdir(parents=True, exist_ok=True)
                    (tree / f).write_bytes(blob.stdout)
        a = podman_test(tag, ref, tests, version_file=d.get("version_file"))
        b = podman_test(tag, cand, tests, version_file=d.get("version_file"))
    differ = sorted(k for k in a["outcomes"] if a["outcomes"][k] == "PASSED" and b["outcomes"].get(k) != "PASSED")
    log(name, "oracle", ok=True, upstream_exit=a["exit"], candidate_exit=b["exit"],
        upstream_failed=a["failed"], candidate_failed=b["failed"], behavioural_differences=differ,
        compared=len(a["outcomes"]))


def recovery(work: Path, exe: str, log: Log) -> None:
    """Failure recovery without a model: a replay mission whose image has no pytest must not pass."""
    name = "humanize"
    repo = work / name / "repo"
    pinned = last(work, "all", "base-image")["image"]
    sh(["podman", "tag", pinned, "localhost/journey-no-pytest:1"], check=True)
    sh([*GIT, "checkout", "-q", "journey"], repo, check=True)
    upstream = last(work, name, "native-check")["upstream_ref"]
    target = DEFECTS[name]["write"][0]
    before = sh([*GIT, "show", f"HEAD:{target}"], repo, check=True).stdout
    after = sh([*GIT, "show", f"{upstream}:{target}"], repo, check=True).stdout.decode()
    replay = work / "recovery-replay.json"
    replay.write_text(json.dumps({"schema": "repo-ai.replay/1", "label": "explicit simulated proposal: upstream fix",
                                  "edits": [{"path": target, "before_sha256": hashlib.sha256(before).hexdigest(),
                                             "after": after}]}))
    res = repo_ai(exe, repo, "do", DEFECTS[name]["task"], "--agent", "replay", "--replay", str(replay), "--run",
                  "--allow-write", target, "--sandbox", "podman", "--image", "localhost/journey-no-pytest:1", "--json")
    rec = res["record"] or {}
    log(name, "failure-recovery", **res, verdict=rec.get("effective_verdict", rec.get("verdict")))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=["prep", "run", "recovery"])
    ap.add_argument("--work", required=True, type=Path)
    ap.add_argument("--repo-ai", dest="exe")
    ap.add_argument("--only", action="append")
    ap.add_argument("--sessions", type=int, default=4, help="Claude sessions left in the approved budget")
    args = ap.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    log = Log(args.work)
    names = args.only or list(DEFECTS)
    if args.stage == "prep":
        prep(args.work, names, log)
    elif args.stage == "run":
        if not args.exe:
            raise SystemExit("--repo-ai PATH is required")
        run(args.work, names, args.exe, log, min(args.sessions, 4))
    else:
        recovery(args.work, args.exe, log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
