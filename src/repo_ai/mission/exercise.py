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


def measure(workspace: Path, command: str, diff: str, *, timeout_s: float = 120.0) -> dict[str, Any]:
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
        executor = execute.get_executor(workspace, "auto", runner.language, timeout_s=timeout_s)
        if executor.is_container:
            record["reason"] = "line measurement is not implemented for container backends"
            return record
        with isolate.materialize(workspace, label="mission-exercise", listing=listing) as ws:
            bound = executor.in_workspace(ws)
            run_dir = ws.path / RUN_DIR
            run_dir.mkdir(parents=True, exist_ok=True)
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
            for rel, lines_added in sorted(changed.items()):
                eligible = lines_added & exec_by_file.get(rel, set())
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
            return record
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        record["reason"] = type(exc).__name__ + ": " + str(exc)[:160]
        return record
