"""A symbol named like a common English word (`mean`, `update`, `get`) is
found when the prompt is that name alone. Within prose the word stays a
stopword ("what do you mean"), and so does a call or backticked form, which
would change the ranking of 31 of Session A's 1,375 holdout queries
unmeasured: a documented limit for the release, to evaluate after it. Found
by the release-freeze journey check on the built wheel (2026-10-26): `repo-ai
context "mean"` returned nothing in a repository that defines `mean`."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from conftest import run_cli
from repo_ai.retrieval import classify


@pytest.mark.parametrize("prompt,name", [("mean", "mean"), ("get", "get"), (" update ", "update")])
def test_a_prompt_that_is_one_stopword_name_is_an_identifier(prompt: str, name: str):
    q = classify(prompt)
    assert name in q.identifiers, q.identifiers


@pytest.mark.parametrize("prompt", ["what do you mean by that", "please update the docs", "get it working",
                                    "mean() raises ZeroDivisionError", "the `update` helper"])
def test_a_stopword_in_prose_stays_a_stopword(prompt: str):
    q = classify(prompt)
    assert not ({"mean", "update", "get"} & set(q.identifiers) | {"mean", "update", "get"} & set(q.terms)), q


def test_context_finds_a_symbol_named_like_a_common_word(tmp_path: Path):
    root = tmp_path / "r"
    (root / "calc").mkdir(parents=True)
    (root / "calc" / "__init__.py").write_text("def mean(xs):\n    return sum(xs) / len(xs)\n")
    (root / "other.py").write_text("def total(xs):\n    return sum(xs)\n")
    git = ["git", "-c", "user.email=t@t", "-c", "user.name=t"]
    for cmd in (["init", "-q"], ["add", "-A"], ["commit", "-qm", "c"]):
        subprocess.run([*git, *cmd], cwd=root, check=True)
    assert run_cli(root, "init", "--agent", "none", "-q").returncode == 0
    for prompt in ("mean", "calc mean empty"):
        out = run_cli(root, "context", prompt).stdout
        assert "calc/__init__.py" in out, (prompt, out[:300])
