"""The proof-evidence contract's machine-readable schema stays in step with
its document (docs/PROOF-EVIDENCE-CONTRACT.md): the same schema id, claim
levels and observation states."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

DOCS = Path(__file__).resolve().parents[1] / "docs"
SCHEMA = DOCS / "schemas" / "proof-evidence-1.schema.json"
DOC = DOCS / "PROOF-EVIDENCE-CONTRACT.md"

pytestmark = pytest.mark.skipif(not SCHEMA.exists() or not DOC.exists(), reason="docs are not in this distribution")


def test_the_schema_and_the_document_name_the_same_levels_and_states():
    schema = json.loads(SCHEMA.read_text("utf-8"))
    doc = DOC.read_text("utf-8")
    assert schema["$id"] == schema["properties"]["schema"]["const"] == "repo-ai.proof-evidence/1"
    assert "`repo-ai.proof-evidence/1`" in doc
    levels = schema["properties"]["claim"]["properties"]["level"]["enum"]
    assert levels[0] == "not_established" and all(f"| `{lv}` |" in doc for lv in levels)
    states = schema["$defs"]["observation"]["properties"]["state"]["enum"]
    assert all(f"`{s}`" in doc for s in states)


def test_a_claim_text_may_not_say_proves_safe_or_correct():
    schema = json.loads(SCHEMA.read_text("utf-8"))
    banned = schema["properties"]["claim"]["properties"]["text"]["not"]["pattern"]
    for text in ("this proves the fix", "the change is safe", "Correct behaviour"):
        assert re.search(banned, text)
    assert not re.search(banned, "tests.test_core fails with this change and passes at the base")
