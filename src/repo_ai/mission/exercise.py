"""Change-exercise assurance: did the frozen tests actually execute the lines the candidate changed?

A mission PASS means "the enumerated frozen tests failed before and pass after". It says nothing about
whether those tests ever ran the new code. A candidate whose changed lines are never executed by the frozen
tests is unconstrained there: any behaviour (right or wrong) would have produced the same PASS. This module
measures that, from the candidate's own diff and one extra sandboxed run of the same command under a
line/block tracer. It uses no hidden requirement and no knowledge of the task.

Levels (never a correctness claim):
  FULL        every executable changed line ran at least once under the frozen tests
  PARTIAL     some executable changed lines never ran (listed as ``path:line``)
  NO_EXECUTABLE_CHANGE  the diff changed no executable line (comments, whitespace, deletions only)
  UNMEASURED  the measurement could not be completed (reason recorded); nothing is implied

With ``per_test`` (a mission run with a frozen requirements declaration) a second, informational record says which
changed lines each test ran: per pytest test (``per_test_granularity: "test"``, a time-window tracer), or per
``node --test`` test FILE (``"file"``: each test file runs alone in its own sandboxed process under V8 coverage, and
the lines it ran, module load included, belong to that file, so to every test in it). It never changes the level.

Backends. The runs use the mission's own sandbox: a host sandbox, or a podman/docker container whose image is pinned
to the digest the verified run recorded (a different digest is UNMEASURED, nothing run). In a container the workspace
is mounted at ``/work`` and the root file system is read-only, so the tracer and V8 write only under
``/work/.repo-ai/run`` (repo-ai's run directory in the workspace), and every path they report is mapped back to a
repo-relative path exactly (`v8lines.inside_rel`, `v8lines.safe_rel`): anything outside the workspace or not in
canonical form is ignored, never credited.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from ..verify import execute, isolate
from ..verify.execute import Executor
from ..verify.testmap import MAX_RECORD_BYTES, RUN_DIR, TRACER

SCHEMA = "repo-ai.change-exercise/1"
MAX_LISTED = 40
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def added_lines(diff: str) -> dict[str, set[int]]:
    """{new path: new-side line numbers} of every added line in a unified diff."""
    out: dict[str, set[int]] = {}
    path: str | None = None
    new_no = 0
    in_hunk = False
    for line in diff.split("\n"):  # git numbers lines by LF only (splitlines also splits on CR, U+2028, ...)
        if line.startswith("diff --git "):
            path, in_hunk = None, False
        elif line.startswith("+++ ") and not in_hunk:
            target = line[4:].split("\t")[0]
            path = None if target == "/dev/null" else (target[2:] if target.startswith("b/") else target)
        elif (m := _HUNK.match(line)) and path is not None:
            new_no, in_hunk = int(m.group(1)), True
        elif in_hunk and path is not None:
            if line.startswith("+"):
                out.setdefault(path, set()).add(new_no)
                new_no += 1
            elif line.startswith(" "):
                new_no += 1
    return out


def _python_executable(text: str) -> set[int] | None:
    try:
        code = compile(text, "<candidate>", "exec", dont_inherit=True)
    except (SyntaxError, ValueError):
        return None
    lines: set[int] = set()
    stack = [code]
    while stack:
        c = stack.pop()
        lines.update(ln for _, _, ln in c.co_lines() if ln)
        stack.extend(k for k in c.co_consts if hasattr(k, "co_lines"))
    return lines


MAX_PER_TEST = 2000  # tests kept in the per-test record (those that ran a changed line)
MAX_STORED_LINES = 2000  # changed lines kept for one test (or one node test file); past it the record is incomplete
MAX_RECORD_LINES = 200_000  # changed lines kept in the whole per-test record


def line_key(item: str) -> tuple[str, int]:
    """Sort "path:line" by path, then by line number (not as text: 10 after 9)."""
    path, _, no = item.rpartition(":")
    return path, int(no) if no.isdigit() else 0


def _finalize(acc: dict[str, set[str]]) -> tuple[dict[str, list[str]], dict[str, int], bool]:
    """(the stored record, {key: true line count} for keys cut at MAX_STORED_LINES or left out whole past
    MAX_RECORD_LINES, whether nothing was cut). The stored record is never cut for display: a line missing from it
    would read as run only by other tests."""
    out: dict[str, list[str]] = {}
    truncated: dict[str, int] = {}
    kept = 0
    for key, lines in acc.items():
        ordered = sorted(lines, key=line_key)
        if len(ordered) > MAX_STORED_LINES:
            truncated[key] = len(ordered)
            ordered = ordered[:MAX_STORED_LINES]
        if kept + len(ordered) > MAX_RECORD_LINES:
            truncated[key] = len(lines)
            continue
        kept += len(ordered)
        out[key] = ordered
    return out, truncated, not truncated


def _clean_files(files: Any) -> dict[str, list[int]]:
    """{repo-relative path: line numbers} from a tracer record (untrusted): only canonical relative paths and
    integer line numbers are kept (the sandbox reports paths relative to its own view of the workspace)."""
    from .v8lines import safe_rel
    if not isinstance(files, dict):
        return {}
    return {rel: [n for n in lines if isinstance(n, int) and not isinstance(n, bool)]
            for rel, lines in files.items() if safe_rel(rel) == rel and isinstance(lines, list)}


def _per_test(trace: dict[str, Any], eligible: dict[str, set[int]]) -> tuple[dict[str, list[str]], bool, dict[str, int]]:
    """({pytest node id: the changed executable lines ("path:line") it ran}, for tests that ran at least one; whether
    the record is complete; {test: true count} for tests whose lines were cut)."""
    acc: dict[str, set[str]] = {}
    complete = trace.get("per_test_complete") is True
    def changed(files: Any) -> set[str]:
        return {f"{rel}:{int(n)}" for rel, lines in _clean_files(files).items()
                for n in lines if n in eligible.get(rel, set())}

    for test, files in trace["per_test"].items():  # lines each test ran itself come first (they fill the cap)
        if not isinstance(test, str) or not isinstance(files, dict) or len(test) > 1000:
            complete = False
            continue
        ran = changed(files)
        if ran:
            if len(acc) >= MAX_PER_TEST:
                complete = False
                break
            acc[test] = ran
    # then each shared fixture run's setup lines, for the tests whose call ran with that run active
    raw_runs, raw_uses = trace.get("fixture_lines"), trace.get("fixture_uses")
    runs: dict[str, Any] = raw_runs if isinstance(raw_runs, dict) else {}
    uses: dict[str, Any] = raw_uses if isinstance(raw_uses, dict) else {}
    by_run = {k: changed(v) for k, v in runs.items()}
    for test, tokens in uses.items():
        if not isinstance(test, str) or not isinstance(tokens, list) or len(test) > 1000:
            continue
        credited = set().union(*(by_run.get(k, set()) for k in tokens if isinstance(k, str))) if tokens else set()
        if not credited:
            continue
        if test not in acc and len(acc) >= MAX_PER_TEST:
            complete = False
            continue
        acc[test] = acc.get(test, set()) | credited
    out, truncated, whole = _finalize(acc)
    return out, complete and whole, truncated


def _per_test_run(record: dict[str, Any], bound: Any, ws: Any, runner: Any, env: dict[str, str], inside: str,
                  changed: dict[str, set[int]], eligible_by_file: dict[str, set[int]], left: float) -> None:
    """A second, slower run only for the per-test record, in the time left after the assurance run. pytest's cache is
    off (a `--lf` or `--sw` in addopts would otherwise run fewer tests than the first run did). A timeout or a missing
    record leaves it out; the caller turns any exception into a reason."""
    watched = sorted(p for p in changed if p.endswith(".py") and "," not in p)
    if not watched or left <= 1:
        record["per_test_reason"] = "no time left for the per-test run" if watched else "no changed python file"
        return
    rest = list(runner.full[1:])
    if rest[:2] == ["-m", "pytest"]:
        rest = [*rest[:2], "-p", "no:cacheprovider", *rest[2:]]
    per_argv = ["python", f"{inside}/{RUN_DIR}/rai_trace.py", "--lines", "--per-test", "--watch", ",".join(watched),
                "--out", f"{inside}/{RUN_DIR}/trace-per-test.json", "--root", inside, "--", *rest]
    per_res = bound.run(per_argv, cwd=runner.cwd, env=env, timeout_s=left, toolchain=runner.language)
    per_raw = None if per_res.timed_out else isolate.read_inside(ws.path, f"{RUN_DIR}/trace-per-test.json",
                                                                MAX_RECORD_BYTES)
    per_trace = json.loads(per_raw.decode("utf-8")) if per_raw else None
    if not (isinstance(per_trace, dict) and isinstance(per_trace.get("per_test"), dict)):
        record["per_test_reason"] = ("the per-test run timed out" if per_res.timed_out
                                     else "the per-test run produced no record")
        return
    record["per_test"], complete, truncated = _per_test(per_trace, eligible_by_file)
    record["per_test_granularity"] = "test"
    if truncated:
        record["per_test_truncated"] = truncated
    # a child process runs code this run cannot see, and an early stop leaves tests unrun
    record["per_test_complete"] = complete and not per_trace.get("spawned") and per_res.exit_code in (0, 1)
    record["changed_outside_tests"] = sorted(
        f"{rel}:{n}" for rel, lines in _clean_files(per_trace.get("outside_tests")).items()
        for n in lines if n in eligible_by_file.get(rel, set()))[:MAX_LISTED]


MAX_NODE_TEST_FILES = 200  # node test files run one by one for the per-file record
NODE_COV_DIR = f"{RUN_DIR}/cov"
MAX_SOURCE_BYTES = 2_000_000
NODE_FILE_MIN_TIMEOUT = 30.0  # seconds a per-file run may always use (within the time left)
JS_SUFFIXES = (".js", ".mjs", ".cjs")


def _node_file_lines(ex: Executor, runner: Any, test: str, texts: dict[str, bytes],
                     eligible_by_file: dict[str, set[int]], timeout_s: float, deadline: float) -> set[str]:
    """The changed executable lines ("path:line") one node test file ran alone, in its own pristine sandboxed
    workspace. Raises `v8lines.Unavailable` when its coverage cannot be trusted to say what ran."""
    from . import v8lines
    assert ex.workspace is not None
    ws = ex.workspace.path
    ident = v8lines.prepare(ws, NODE_COV_DIR)
    env = dict(runner.env)
    env["NODE_V8_COVERAGE"] = f"{ex.inside_root}/{NODE_COV_DIR}"
    res = ex.run(runner.file_argv(test), cwd=runner.cwd, env=env, timeout_s=timeout_s, toolchain="node")
    if res.timed_out:
        raise v8lines.Unavailable(f"its run timed out after {timeout_s:.0f}s (a killed process writes no coverage)")
    if res.exit_code not in (0, 1):  # 1: a test failed, and node still wrote its coverage on exit
        raise v8lines.Unavailable(f"its run ended abnormally (exit {res.exit_code})")
    folded = v8lines.fold(ws, NODE_COV_DIR, ident, ex.inside_root,
                          {rel: data.decode("utf-8") for rel, data in texts.items()}, present={test}, deadline=deadline)
    if test not in folded.seen:
        raise v8lines.Unavailable("its coverage does not include the test file itself")
    hits: set[str] = set()
    for rel, original in texts.items():
        try:
            after = isolate.read_inside(ws, rel, MAX_SOURCE_BYTES)
        except isolate.ReportTooLarge:
            after = None
        if after != original:
            raise v8lines.Unavailable(f"{rel} changed during its run")
        acc = folded.accumulators[rel]
        if not acc.entries:
            continue  # valid coverage that never loaded this file: it ran none of its lines
        executable, ran = acc.line_status()
        hits.update(f"{rel}:{n}" for n in ran & executable & eligible_by_file.get(rel, set()))
    return hits


def _per_file_node_run(record: dict[str, Any], template: Executor, runner: Any, files: list[str],
                       changed: dict[str, set[int]], eligible_by_file: dict[str, set[int]], left: float,
                       first: list[str] | None = None) -> None:
    """The per-test record of a `node --test` mission, per test FILE: each file runs alone, in a fresh copy of the
    workspace taken before anything ran, with NODE_V8_COVERAGE pointing at a directory repo-ai created. The files
    holding declared tests (`first`) run first; each run may use at most the larger of NODE_FILE_MIN_TIMEOUT and twice
    an equal share of the time left over the files still to run, so one hanging file cannot use up the rest. A file
    whose run or coverage fails in any way is listed as unavailable with the reason, never as having run nothing.
    Container backends never get here (`measure` returns first)."""
    from . import v8lines
    from ..verify.execute import release
    assert template.workspace is not None
    record["per_test_granularity"] = "file"
    watched = sorted(p for p in changed if p.endswith(JS_SUFFIXES))
    if not watched:
        record["per_test_reason"] = "no changed JavaScript file"
        return
    if not files:
        record["per_test_reason"] = "no node test file was discovered"
        return
    texts: dict[str, bytes] = {}
    for rel in watched:
        try:
            data = isolate.read_inside(template.workspace.path, rel, MAX_SOURCE_BYTES)
        except isolate.ReportTooLarge:
            data = None
        if data is None:
            record["per_test_reason"] = f"{rel} could not be read back"
            return
        try:
            data.decode("utf-8")
        except UnicodeDecodeError:
            record["per_test_reason"] = f"{rel} is not UTF-8, so V8's offsets cannot be mapped to its lines"
            return
        texts[rel] = data
    preferred = set(first or [])
    ordered = [f for f in files if f in preferred] + [f for f in files if f not in preferred]
    todo = ordered[:MAX_NODE_TEST_FILES]
    deadline = time.monotonic() + left
    acc: dict[str, set[str]] = {}
    measured: list[str] = []
    unavailable: dict[str, str] = {}
    for n, test in enumerate(todo):
        remaining = deadline - time.monotonic()
        if remaining <= 1:
            unavailable[test] = "no time was left for its run"
            continue
        timeout = min(remaining, max(NODE_FILE_MIN_TIMEOUT, 2 * remaining / (len(todo) - n)))
        ex: Executor | None = None
        try:
            ex = template.fresh()
            lines = _node_file_lines(ex, runner, test, texts, eligible_by_file, timeout, deadline)
        except v8lines.Unavailable as exc:
            unavailable[test] = str(exc)
            continue
        except Exception as exc:  # noqa: BLE001 - one file's failure must not drop the others' record
            unavailable[test] = "its run could not be measured: " + type(exc).__name__
            continue
        finally:
            if ex is not None:
                release([ex])
        measured.append(test)
        if lines:
            acc[test] = lines
    record["per_test"], truncated, whole = _finalize(acc)
    if truncated:
        record["per_test_truncated"] = truncated
    for test in truncated:
        if test not in record["per_test"]:  # left out whole: its lines are unknown, not none
            measured.remove(test)
            unavailable[test] = f"its {truncated[test]} changed lines were cut from the record (over " \
                                f"{MAX_RECORD_LINES} in all)"
    record["per_test_measured"] = measured
    record["per_test_unavailable"] = unavailable
    if len(files) > MAX_NODE_TEST_FILES:
        record["per_test_reason"] = (f"only {MAX_NODE_TEST_FILES} of {len(files)} test files were run (those with "
                                     "declared tests first); the others are not measured")
    record["per_test_complete"] = whole and not unavailable and len(files) <= MAX_NODE_TEST_FILES


def measure(workspace: Path, command: str, diff: str, *, timeout_s: float = 120.0,
            project_root: Path | None = None, sandbox_preference: str = "auto", image: str = "",
            per_test: bool = False, declared_files: list[str] | None = None,
            expected_image_digest: str = "", expected_backend: str = "") -> dict[str, Any]:
    """Run `command` once more over a pristine copy of `workspace` (the verified candidate) under a
    line tracer and compare with the lines `diff` added. Never raises: failure is ``UNMEASURED``.
    `declared_files`: node test files holding declared tests, run first for the per-file record.
    `expected_image_digest`: in a container, the image digest the verified run used; any other is refused.
    `expected_backend`: the sandbox backend the verified run used (`seatbelt`, `bwrap`, `podman`, `docker`); a
    measurement that would run in another (`--sandbox auto` choosing differently) is refused."""
    from . import v8lines, verification
    record: dict[str, Any] = {"schema": SCHEMA, "assurance": "UNMEASURED", "reason": "", "changed_lines": 0,
                              "unexercised": [], "files": {}}
    changed = {p: ls for p, ls in added_lines(diff).items() if Path(p).suffix in {".py", ".js", ".mjs", ".cjs"}}
    if not changed:
        record.update(assurance="NO_EXECUTABLE_CHANGE", reason="diff adds no line to a supported source file")
        return record
    ws = None
    template: Executor | None = None
    try:
        runner = verification._runner(command)
        listing = isolate.worktree_files(workspace)
        verification.container_layout(workspace, runner, listing[0], sandbox_preference)
        executor = execute.get_executor(workspace, sandbox_preference, runner.language, timeout_s=timeout_s,
                                        interpreter_root=project_root, image=image)
        record["backend"] = executor.backend.name
        if expected_backend and executor.backend.name != expected_backend:
            record["reason"] = (f"the measurement would run in {executor.backend.name}, but the verified run used "
                                f"{expected_backend}; nothing was run")
            return record
        if executor.is_container:
            # the same image bytes as the verified run, pinned so a moved tag cannot change them between runs
            pinned = verification.pin_container_image(executor, runner.language)
            record["container"] = pinned
            if expected_image_digest and pinned["image_digest"] != expected_image_digest:
                record["reason"] = ("the container image is not the one the verified run used "
                                    f"({pinned['image_digest'][:19]} != {expected_image_digest[:19]}); nothing was run")
                return record
        with isolate.materialize(workspace, label="mission-exercise", listing=listing) as ws:
            bound = executor.in_workspace(ws)
            started = time.monotonic()  # the per-file copy below counts against the measurement's time
            if per_test and runner.kind == "node" and any(p.endswith(JS_SUFFIXES) for p in changed):
                # every per-file run starts from a copy taken now, before the assurance run changes anything; a copy
                # that cannot be made only leaves the per-file record out, never the assurance
                try:
                    template = bound.fresh()
                except (OSError, RuntimeError) as exc:
                    record["per_test_reason"] = "the workspace copy for the per-file runs failed: " + type(exc).__name__
            run_dir = isolate.run_dir(ws.path, RUN_DIR)
            inside = bound.inside_root
            env = dict(runner.env)
            cov_ident = None
            if runner.kind == "node":
                cov_ident = v8lines.prepare(ws.path, NODE_COV_DIR)
                env["NODE_V8_COVERAGE"] = f"{inside}/{NODE_COV_DIR}"
                argv = list(runner.full)
            else:
                import shutil
                shutil.copy2(TRACER, run_dir / "rai_trace.py")
                argv = ["python", f"{inside}/{RUN_DIR}/rai_trace.py", "--lines", "--out", f"{inside}/{RUN_DIR}/trace.json",
                        "--root", inside, "--", *runner.full[1:]]
            res = bound.run(argv, cwd=runner.cwd, env=env, timeout_s=timeout_s, toolchain=runner.language)
            if res.timed_out:
                record["reason"] = "measurement run timed out"
                return record
            texts: dict[str, str] = {}
            for rel in changed:
                data = isolate.read_inside(ws.path, rel, MAX_SOURCE_BYTES)
                if data is None:
                    record["reason"] = "a changed file could not be read back"
                    return record
                try:  # V8 offsets index the source node decoded: a lossy decoding would shift them
                    texts[rel] = data.decode("utf-8", "strict" if runner.kind == "node" else "replace")
                except UnicodeDecodeError:
                    record["reason"] = f"{rel} is not UTF-8, so V8's offsets cannot be mapped to its lines"
                    return record
            executed_by_file: dict[str, set[int]] = {}
            never_by_file: dict[str, set[int]] = {}
            exec_by_file: dict[str, set[int]] = {}
            trace: Any = {}
            if runner.kind == "node":
                assert cov_ident is not None
                # coverage the suite wrote is untrusted: bounded and link-free (`Unavailable` is UNMEASURED); a
                # malformed file or entry is skipped, which can only report more lines as never run
                # each entry is folded into its file's bit map as it is read: a suite writes one per test file
                parse_by = time.monotonic() + max(30.0, timeout_s - (time.monotonic() - started))
                # every node child process a test starts writes its own file too, so the count is not derived from
                # the suite: bytes, ranges and the deadline bound the work; the ceiling bounds the listing
                folded = v8lines.fold(ws.path, NODE_COV_DIR, cov_ident, inside, texts, deadline=parse_by,
                                      lenient=True, max_files=v8lines.MAX_FILES_CEILING)
                for rel in texts:
                    exec_by_file[rel], never_by_file[rel] = folded.accumulators[rel].never_run()
            else:
                raw = isolate.read_inside(ws.path, f"{RUN_DIR}/trace.json", MAX_RECORD_BYTES)
                trace = json.loads(raw.decode("utf-8")) if raw else {}
                raw_lines = trace.get("lines") if isinstance(trace, dict) else None
                if not isinstance(raw_lines, dict):
                    record["reason"] = "tracer produced no line record"
                    return record
                lines = _clean_files(raw_lines)
                python, events = trace.get("python"), trace.get("line_events")
                if isinstance(python, list) and len(python) == 3 and all(isinstance(x, int) for x in python) \
                        and events in {"sys.monitoring", "settrace"}:
                    record["tracer"] = {"python": ".".join(map(str, python)), "line_events": events}
                for rel, text in texts.items():
                    executable = _python_executable(text)
                    if executable is None:
                        record["reason"] = "a changed python file does not compile"
                        return record
                    exec_by_file[rel] = executable
                    executed_by_file[rel] = set(lines.get(rel, []))
                    never_by_file[rel] = executable - executed_by_file[rel]
            unexercised: list[str] = []
            total = 0
            eligible_by_file = {rel: lines_added & exec_by_file.get(rel, set()) for rel, lines_added in changed.items()}
            for rel in sorted(changed):
                eligible = eligible_by_file[rel]
                missed = eligible & never_by_file.get(rel, set())
                total += len(eligible)
                unexercised.extend(f"{rel}:{n}" for n in sorted(missed))
                record["files"][rel] = {"changed_executable": len(eligible), "unexercised": len(missed)}
            record.update(changed_lines=total, unexercised=unexercised[:MAX_LISTED], unexercised_count=len(unexercised),
                          reason="", exit_code=res.exit_code)
            if total == 0:
                record["assurance"] = "NO_EXECUTABLE_CHANGE"
            else:
                record["assurance"] = "PARTIAL" if unexercised else "FULL"
            if per_test and runner.kind in {"pytest", "node"}:
                try:  # informational: nothing in it may change the assurance just recorded
                    left = timeout_s - (time.monotonic() - started)
                    if runner.kind == "pytest":
                        _per_test_run(record, bound, ws, runner, env, inside, changed, eligible_by_file, left)
                    elif template is not None:
                        _per_file_node_run(record, template, runner, runner.test_files(listing[0], workspace),
                                           changed, eligible_by_file, left, declared_files)
                except Exception as exc:  # noqa: BLE001 - the per-test record is optional
                    for key in ("per_test", "per_test_complete", "per_test_measured", "per_test_unavailable",
                                "per_test_truncated"):
                        record.pop(key, None)
                    record["per_test_reason"] = "the per-test run failed: " + type(exc).__name__
            return record
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        record["reason"] = type(exc).__name__ + ": " + str(exc)[:160]
        return record
    finally:
        if template is not None:
            from ..verify.execute import release
            release([template])
