"""Claim taxonomy: what a mission result does and does not establish.

A passing frozen suite is evidence that *those tests* passed. It is never a statement that the task is
correct. This module adds an additive, deterministic disclosure on top of the existing verdict:

  headline  OBSERVED_TESTS_PASS  fresh PASS and every stated requirement is lexically echoed by the tests
            ASSURANCE_PARTIAL    fresh PASS but a requirement is only weakly echoed by the tests, or the
                                 changed lines were not (fully) exercised
            CLAIM_UNVERIFIED     nothing to compare (no stated requirement or no test text)
            INCONCLUSIVE         not a usable PASS/FAIL (blocked, unchecked freshness, ...)
            FAIL / STALE         failing result / evidence no longer matches the source
  task_correct is always CLAIM_UNVERIFIED: repo-ai never certifies task correctness.

Requirement erasure: a candidate that deletes documentation stating a requirement (a docstring or comment line with
words such as "raise", "must", "never", "only", "reject") is named, and a clean PASS drops to ASSURANCE_PARTIAL.
Observed live: a local model dropped "Raise ValueError if lo > hi" from a docstring together with the behaviour, and
the visible tests passed. Read from the unified diff only; a docstring that starts before a hunk's context is a blind
spot.

The requirement-to-test mapping is a lexical heuristic (words of each stated requirement versus words of the
non-comment test text). It can only *lower* confidence; it cannot prove coverage, and it is blind to a test
that mentions a word without asserting it. It is deliberately conservative: on the four abc-v1 tasks every
one comes out ASSURANCE_PARTIAL, so it does NOT single out node-slug (no threshold was tuned on that
counterexample); OBSERVED_TESTS_PASS is reachable only when every key term of every stated requirement
appears in the tests. The recorded abc-v1 ``node-slug`` false green (the visible tests
never state "unique across the whole list") is the motivating counterexample.
"""
from __future__ import annotations

import re
from typing import Any

SCHEMA = "repo-ai.claims/1"
MAX_OBJECTIVE = 4000
MAX_REQUIREMENTS = 12
MAX_TEXT = 200
MAX_TEST_BYTES = 1_000_000
MAX_TERMS = 12

_STOP = frozenset("""
the and for with that this from into must should shall when then than also only each every any all not are was
were been being have has had its their there here out off over under per via can could would will may might
keep everything else exports export file files function functions method methods code test tests make makes
made ensure ensures does doing done use used using new old add adds added fix fixes fixed update updates
""".split())
# General English words that widen or restrict the SCOPE of a requirement. When a requirement uses one and the tests
# never use the same word, the visible tests may be silent on exactly the clause that makes the requirement hard.
# The list is fixed, language-general and was not derived from any benchmark task; it is a prompt for a human,
# never evidence of a defect or of correctness.
_QUALIFIERS = frozenset("""
whole entire every each all any never always only exactly across none nothing least most both either neither
same twice once concurrent concurrently simultaneously unique distinct idempotent
""".split())
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
_SPLIT = re.compile(r"(?<=[.!?;])\s+|\n+")
_COMMENT = re.compile(r"(?m)(^\s*#.*$|(?<![:\w])//.*$)")
_BLOCK = re.compile(r"/\*.*?\*/", re.S)


def _clean(text: str, limit: int) -> str:
    return _CTRL.sub("", text)[:limit]


def _stem(word: str) -> str:
    for suffix in ("ing", "es", "ed", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _tokens(text: str) -> set[str]:
    out: set[str] = set()
    for word in _WORD.findall(text):
        parts = [p.lower() for p in _CAMEL.findall(word)] or [word.lower()]
        out.update(_stem(p) for p in parts)
        out.add(_stem(word.lower()))
    return out


_QUALIFIER_STEMS = frozenset(_stem(w) for w in _QUALIFIERS)


def _requirement_terms(sentence: str) -> list[str]:
    terms: list[str] = []
    for word in _WORD.findall(sentence):
        for part in [p.lower() for p in _CAMEL.findall(word)] or [word.lower()]:
            if len(part) >= 3 and part not in _STOP and part.isalpha():
                stem = _stem(part)
                if stem not in terms:
                    terms.append(stem)
    return terms[:MAX_TERMS]


def _test_vocabulary(tests: dict[str, str]) -> set[str]:
    vocabulary: set[str] = set()
    budget = MAX_TEST_BYTES
    for text in tests.values():
        if budget <= 0:
            break
        chunk = text[:budget]
        budget -= len(chunk)
        vocabulary |= _tokens(_COMMENT.sub("", _BLOCK.sub("", chunk)))
    return vocabulary


def requirements(objective: str, tests: dict[str, str]) -> list[dict[str, Any]]:
    """Per-sentence requirement echo: STRONG (all key terms in tests), WEAK (some), NONE."""
    vocabulary = _test_vocabulary(tests)
    rows: list[dict[str, Any]] = []
    for sentence in _SPLIT.split(_clean(objective, MAX_OBJECTIVE)):
        text = sentence.strip()
        terms = _requirement_terms(text)
        if not terms:
            continue
        unmatched = [t for t in terms if t not in vocabulary]
        evidence = "STRONG" if not unmatched else ("NONE" if len(unmatched) == len(terms) else "WEAK")
        qualifiers = [t for t in unmatched if t in _QUALIFIER_STEMS]
        rows.append({"text": text[:MAX_TEXT], "terms": terms, "unmatched_terms": unmatched, "evidence": evidence,
                     "unechoed_qualifiers": qualifiers})
        if len(rows) >= MAX_REQUIREMENTS:
            break
    return rows


_REQUIREMENT_WORDS = re.compile(
    r"(?i)\b(raises?|errors?|exceptions?|must|shall|should|never|always|only|reject\w*|invalid|valid\w*|empty|"
    r"unless|at (?:least|most)|if)\b")
_DOC_FILES = (".py", ".pyi", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx")


def removed_requirement_text(diff: str) -> list[dict[str, str]]:
    """Documentation lines a candidate removed (docstrings, comments) that state a requirement and that the candidate
    did not re-add verbatim. Heuristic, from the diff alone; a prompt for a human, never evidence of a defect."""
    found: list[dict[str, str]] = []
    path = ""
    in_doc = False
    added: set[str] = set()
    removed: list[tuple[str, str]] = []
    for line in diff.splitlines():
        if line.startswith("diff --git "):
            path, in_doc = "", False
            continue
        if line.startswith("+++ "):
            target = line[4:].strip()
            path = target[2:] if target.startswith("b/") else target
            continue
        if line.startswith(("--- ", "index ", "new file", "deleted file", "similarity", "rename ", "Binary")):
            continue
        if line.startswith("@@"):
            in_doc = False  # unknown at a hunk start: only docstrings that open inside the hunk are tracked
            continue
        if not path.endswith(_DOC_FILES) or not line:
            continue
        mark, text = line[0], line[1:]
        if mark == "+":
            added.add(" ".join(text.split()))
            continue
        if mark not in {" ", "-"}:
            continue
        stripped = text.strip()
        quotes = stripped.count('"""') + stripped.count("\'\'\'")
        is_doc = in_doc or quotes > 0
        if quotes % 2:
            in_doc = not in_doc
        is_comment = stripped.startswith(("#", "//", "*", "/*"))
        if mark == "-" and (is_doc or is_comment) and _REQUIREMENT_WORDS.search(stripped):
            removed.append((path, stripped))
    for file, text in removed:
        if " ".join(text.split()) not in added and len(found) < 8:
            found.append({"file": file, "text": _clean(text.strip("#/*\"' "), 160)})
    return found


def assess(objective: str, tests: dict[str, str], *, verdict: str, freshness: str,
           exercise: dict[str, Any] | None, diff: str = "") -> dict[str, Any]:
    rows = requirements(objective, tests) if tests else []
    erased = removed_requirement_text(diff) if diff else []
    notes: list[str] = ["repo-ai does not certify that the task is correct; it reports what the frozen tests observed"]
    exercise_level = (exercise or {}).get("assurance")
    weak = [r for r in rows if r["evidence"] != "STRONG"]
    if freshness == "stale":
        headline = "STALE"
    elif freshness != "fresh":
        headline = "INCONCLUSIVE"
    elif verdict == "FAIL":
        headline = "FAIL"
    elif verdict != "PASS":
        headline = "INCONCLUSIVE"
    elif not rows:
        headline = "CLAIM_UNVERIFIED"
        notes.append("no stated requirement could be compared with the test text")
    elif weak or erased or exercise_level in {"PARTIAL", "UNMEASURED"}:
        headline = "ASSURANCE_PARTIAL"
    else:
        headline = "OBSERVED_TESTS_PASS"
    for row in weak:
        notes.append(f"requirement {'weakly' if row['evidence'] == 'WEAK' else 'not'} echoed by the tests (not in test text: "
                     f"{', '.join(row['unmatched_terms'][:6])}): {row['text'][:80]!r}")
    scoped = sorted({q for r in rows for q in r["unechoed_qualifiers"]})
    if scoped:
        notes.append("scope/quantifier words used by a requirement but absent from the tests (heuristic prompt to check "
                     "the unstated clause; not a finding): " + ", ".join(scoped[:8]))
    if exercise_level in {"PARTIAL", "UNMEASURED"}:
        notes.append(f"change-exercise {exercise_level}: some changed lines were not shown to run under the frozen tests")
    for item in erased:
        notes.append(f"the candidate removed documentation that states a requirement ({item['file']}): {item['text']!r}; "
                     "check the behaviour it described is still met (tests passing does not show it)")
    return {"schema": SCHEMA, "headline": headline, "task_correct": "CLAIM_UNVERIFIED",
            "unechoed_qualifiers": scoped, "requirements": rows, "removed_requirement_text": erased,
            "notes": [_clean(n, 300) for n in notes]}
