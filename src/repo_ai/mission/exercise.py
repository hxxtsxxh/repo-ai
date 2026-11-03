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
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from ..verify import execute, isolate
from ..verify.testmap import MAX_RECORD_BYTES, RUN_DIR, TRACER, _node_scripts

SCHEMA = "repo-ai.change-exercise/1"
MAX_LISTED = 40
_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def added_lines(diff: str) -> dict[str, set[int]]:
    """{new path: new-side line numbers} of every added line in a unified diff."""
    out: dict[str, set[int]] = {}
    path: str | None = None
    new_no = 0
    in_hunk = False
    for line in diff.splitlines():
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


def _node_line_status(text: str, reports: list[list[dict[str, Any]]]) -> tuple[set[int], set[int]]:
    """(executable lines, lines with a never-run character) for one file from V8 block coverage.

    A line is unexercised when any non-blank character on it lies in a block that ran zero times in every
    report; an executable line is any non-blank, non-comment line. Block precision means a never-taken
    branch on an otherwise executed line (``while (c) n++;`` with ``n++`` never run) is still reported.
    """
    starts = [0]
    for i, ch in enumerate(text):
        if ch == "\n":
            starts.append(i + 1)
    ran = bytearray(len(text) + 1)
    seen_any = False
    for functions in reports:
        mark = bytearray(len(text) + 1)
        for fn in functions:
            for r in fn.get("ranges") or []:
                s, e = int(r.get("startOffset", 0)), min(int(r.get("endOffset", 0)), len(text))
                mark[s:e] = (b"\x01" if int(r.get("count", 0)) > 0 else b"\x00") * max(e - s, 0)
                seen_any = True
        for i, v in enumerate(mark):
            if v:
                ran[i] = 1
    executable: set[int] = set()
    never: set[int] = set()
    for no, begin in enumerate(starts, start=1):
        end = starts[no] - 1 if no < len(starts) else len(text)
        seg = text[begin:end]
        stripped = seg.strip()
        if not stripped or stripped.startswith(("//", "/*", "*")) or not re.search(r"\w", stripped):
            continue
        executable.add(no)
        if not seen_any:
            never.add(no)
            continue
        for off in range(begin, end):
            if not text[off].isspace() and not ran[off]:
                never.add(no)
                break
    return executable, never


MAX_PER_TEST = 2000  # tests kept in the per-test record (those that ran a changed line)


def _per_test(trace: dict[str, Any], eligible: dict[str, set[int]]) -> tuple[dict[str, list[str]], bool]:
    """{pytest node id: the changed executable lines ("path:line") it ran}, for tests that ran at least one."""
    out: dict[str, list[str]] = {}
    complete = trace.get("per_test_complete") is True
    def changed(files: Any) -> set[str]:
        return {f"{rel}:{int(n)}" for rel, lines in (files.items() if isinstance(files, dict) else ())
                if isinstance(lines, list) for n in lines if isinstance(n, int) and n in eligible.get(rel, set())}

    for test, files in trace["per_test"].items():  # lines each test ran itself come first (they fill the cap)
        if not isinstance(test, str) or not isinstance(files, dict) or len(test) > 1000:
            complete = False
            continue
        ran = changed(files)
        if ran:
            if len(out) >= MAX_PER_TEST:
                complete = False
                break
            out[test] = sorted(ran)[:MAX_LISTED]
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
        if test not in out and len(out) >= MAX_PER_TEST:
            complete = False
            continue
        out[test] = sorted(set(out.get(test, [])) | credited)[:MAX_LISTED]
    return out, complete


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
    record["per_test"], complete = _per_test(per_trace, eligible_by_file)
    # a child process runs code this run cannot see, and an early stop leaves tests unrun
    record["per_test_complete"] = complete and not per_trace.get("spawned") and per_res.exit_code in (0, 1)
    raw_outside = per_trace.get("outside_tests")
    outside: dict[str, Any] = raw_outside if isinstance(raw_outside, dict) else {}
    record["changed_outside_tests"] = sorted(
        f"{rel}:{int(n)}" for rel, lines in outside.items() if isinstance(lines, list)
        for n in lines if isinstance(n, int) and n in eligible_by_file.get(rel, set()))[:MAX_LISTED]


def measure(workspace: Path, command: str, diff: str, *, timeout_s: float = 120.0,
            project_root: Path | None = None, sandbox_preference: str = "auto", image: str = "",
            per_test: bool = False) -> dict[str, Any]:
    """Run `command` once more over a pristine copy of `workspace` (the verified candidate) under a
    line tracer and compare with the lines `diff` added. Never raises: failure is ``UNMEASURED``."""
    from . import verification
    record: dict[str, Any] = {"schema": SCHEMA, "assurance": "UNMEASURED", "reason": "", "changed_lines": 0,
                              "unexercised": [], "files": {}}
    changed = {p: ls for p, ls in added_lines(diff).items() if Path(p).suffix in {".py", ".js", ".mjs", ".cjs"}}
    if not changed:
        record.update(assurance="NO_EXECUTABLE_CHANGE", reason="diff adds no line to a supported source file")
        return record
    ws = None
    try:
        runner = verification._runner(command)
        listing = isolate.worktree_files(workspace)
        verification.container_layout(workspace, runner, listing[0], sandbox_preference)
        executor = execute.get_executor(workspace, sandbox_preference, runner.language, timeout_s=timeout_s,
                                        interpreter_root=project_root, image=image)
        if executor.is_container:
            record["reason"] = "line measurement is not implemented for container backends"
            return record
        with isolate.materialize(workspace, label="mission-exercise", listing=listing) as ws:
            bound = executor.in_workspace(ws)
            run_dir = isolate.run_dir(ws.path, RUN_DIR)
            inside = bound.inside_root
            env = dict(runner.env)
            if runner.kind == "node":
                env["NODE_V8_COVERAGE"] = f"{inside}/{RUN_DIR}/cov"
                argv = list(runner.full)
            else:
                import shutil
                shutil.copy2(TRACER, run_dir / "rai_trace.py")
                argv = ["python", f"{inside}/{RUN_DIR}/rai_trace.py", "--lines", "--out", f"{inside}/{RUN_DIR}/trace.json",
                        "--root", inside, "--", *runner.full[1:]]
            started = time.monotonic()
            res = bound.run(argv, cwd=runner.cwd, env=env, timeout_s=timeout_s, toolchain=runner.language)
            if res.timed_out:
                record["reason"] = "measurement run timed out"
                return record
            texts: dict[str, str] = {}
            for rel in changed:
                data = isolate.read_inside(ws.path, rel, 2_000_000)
                if data is None:
                    record["reason"] = "a changed file could not be read back"
                    return record
                texts[rel] = data.decode("utf-8", "replace")
            executed_by_file: dict[str, set[int]] = {}
            never_by_file: dict[str, set[int]] = {}
            exec_by_file: dict[str, set[int]] = {}
            trace: Any = {}
            if runner.kind == "node":
                per_file: dict[str, list[list[dict[str, Any]]]] = {}
                for rel, functions in _node_scripts(ws.path, inside):
                    per_file.setdefault(rel, []).append(functions)
                for rel, text in texts.items():
                    exec_by_file[rel], never_by_file[rel] = _node_line_status(text, per_file.get(rel, []))
            else:
                raw = isolate.read_inside(ws.path, f"{RUN_DIR}/trace.json", MAX_RECORD_BYTES)
                trace = json.loads(raw.decode("utf-8")) if raw else {}
                lines = trace.get("lines") if isinstance(trace, dict) else None
                if not isinstance(lines, dict):
                    record["reason"] = "tracer produced no line record"
                    return record
                for rel, text in texts.items():
                    executable = _python_executable(text)
                    if executable is None:
                        record["reason"] = "a changed python file does not compile"
                        return record
                    exec_by_file[rel] = executable
                    executed_by_file[rel] = {int(x) for x in lines.get(rel, [])}
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
            if per_test and runner.kind == "pytest":
                try:  # informational: nothing in it may change the assurance just recorded
                    _per_test_run(record, bound, ws, runner, env, inside, changed, eligible_by_file,
                                  timeout_s - (time.monotonic() - started))
                except Exception as exc:  # noqa: BLE001 - the per-test record is optional
                    record.pop("per_test", None)
                    record["per_test_reason"] = "the per-test run failed: " + type(exc).__name__
            return record
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        record["reason"] = type(exc).__name__ + ": " + str(exc)[:160]
        return record
