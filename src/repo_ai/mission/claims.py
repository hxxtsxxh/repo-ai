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
words such as "raise", "must", "never", "reject") is named, and a clean PASS drops to ASSURANCE_PARTIAL.
Observed live: a local model dropped "Raise ValueError if lo > hi" from a docstring together with the behaviour, and
the visible tests passed. Python lines are placed with the parser on the base file when the runtime supplies it;
otherwise (and for JS/TS) a diff-only heuristic is used, for which a docstring opened before a hunk's context is a blind
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
import unicodedata
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
    # control characters and Unicode format characters (bidi overrides, zero-width) never reach a note
    text = _CTRL.sub("", text)
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")[:limit]


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
    r"(?i)\b(raises?|raising|throws?|must|shall|never|always|reject\w*|invalid|forbid\w*|required|"
    r"at (?:least|most)|no (?:more|less|fewer) than)\b")
_NOTE_PREFIX = re.compile(r"(?i)^(todo|fixme|xxx|hack|note)\b")
_SECTION_HEADER = re.compile(r"(?i)^(raises|throws|exceptions|errors|returns?|args|arguments|parameters|yields)\s*:?$|^[-=]{3,}$")
_PY_FILES = (".py", ".pyi")
_JS_FILES = (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx")
_DOC_OPEN = re.compile(r"""^[rRbBuUfF]{0,2}("{3}|'{3})""")
_HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")
_DECORATION = re.compile(r"""^\s*(?:#+|//+|/\*+|\*+/?|[rRbBuUfF]{0,2}"{3}|[rRbBuUfF]{0,2}'{3})\s*|\s*(?:\*/|"{3}|'{3})\s*$""")


def _plain(text: str) -> str:
    """Documentation text without comment/quote decoration, whitespace collapsed, for moved-text matching."""
    return " ".join(_DECORATION.sub("", text).split()).lower()


def python_doc_lines(source: str) -> set[int] | None:
    """1-based line numbers of docstrings (module, class, function) and comments in Python source, or None if it
    does not parse. Used to place removed lines exactly instead of guessing from the hunk."""
    import ast
    import io
    import tokenize
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    try:
        for tok in tokenize.generate_tokens(io.StringIO(source).readline):
            if tok.type == tokenize.COMMENT:
                lines.add(tok.start[0])
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return lines


def removed_requirement_text(diff: str, base_source=None) -> list[dict[str, str]]:
    """Documentation lines a candidate removed (docstrings, comments) that state a requirement and whose text does not
    reappear among the file's added lines. Heuristic, from the diff alone; a prompt for a human, never evidence.

    Python docstrings are recognised only when they open as the first statement after a `def`/`class` line (or at the
    top of the file) inside the hunk; a hunk that starts inside a docstring is not guessed at (a blind spot, like a
    docstring opened before the hunk's context). With ``base_source(path) -> str | None`` (the file at the mission's
    base), Python lines are placed exactly with the parser instead, which removes that blind spot."""
    exact: dict[str, set[int] | None] = {}
    old_no = 0
    removed: list[tuple[str, str]] = []
    added: dict[str, list[str]] = {}
    path = ""
    old_left = new_left = 0
    in_doc = False
    doc_quote = ""
    prev_old = ""
    first_old = False
    for raw in diff.split("\n"):
        line = raw[:-1] if raw.endswith("\r") else raw
        if old_left <= 0 and new_left <= 0:  # between hunks: headers
            if line.startswith("diff --git "):
                path = ""
            elif line.startswith("+++ "):
                target = line[4:].strip().strip('"')
                if target != "/dev/null":  # a whole-file deletion keeps the old path from its `---` line
                    path = target[2:] if target.startswith("b/") else target
            elif line.startswith("--- ") and not path:
                source = line[4:].strip().strip('"')
                path = source[2:] if source.startswith("a/") else ""  # whole-file deletion: judge the old path
            else:
                m = _HUNK.match(line)
                if m:
                    old_no = int(line[4:].split(",")[0].split(" ")[0]) - 1
                    old_left = int(m.group(1) or 1)
                    new_left = int(m.group(2) or 1)
                    in_doc, doc_quote, prev_old = False, "", ""
                    first_old = line.startswith("@@ -1,") or line.startswith("@@ -1 ") or line.startswith("@@ -0,")
            continue
        if line.startswith("\\"):
            continue  # "\ No newline at end of file"
        mark, text = (line[0], line[1:]) if line else (" ", "")
        if mark == "+":
            new_left -= 1
            added.setdefault(path, []).append(_plain(text))
            continue
        if mark not in {" ", "-"}:
            old_left = new_left = 0
            continue
        old_left -= 1
        old_no += 1
        if mark == " ":
            new_left -= 1
        if not path.endswith(_PY_FILES + _JS_FILES):
            continue
        stripped = text.strip()
        is_doc = False
        if path.endswith(_PY_FILES) and base_source is not None and path not in exact:
            base_text: str | None
            try:
                base_text = base_source(path)
            except Exception:  # noqa: BLE001 - an unreadable base only falls back to the heuristic
                base_text = None
            exact[path] = python_doc_lines(base_text) if isinstance(base_text, str) else None
        known = exact.get(path) if path.endswith(_PY_FILES) else None
        if known is not None:
            is_doc = old_no in known
            is_comment = False
        elif path.endswith(_PY_FILES):
            if in_doc:
                is_doc = True
                if doc_quote in stripped:
                    in_doc = False
            else:
                opener = _DOC_OPEN.match(stripped)
                if opener and (prev_old.rstrip().endswith(":") or (first_old and not prev_old)):
                    is_doc = True
                    doc_quote = opener.group(1)
                    rest = stripped[opener.end():]
                    in_doc = doc_quote not in rest
            is_comment = stripped.startswith("#")
        else:
            is_comment = stripped.startswith(("//", "/*", "*"))
        if stripped:
            prev_old = text
        if mark == "-" and (is_doc or is_comment) and _REQUIREMENT_WORDS.search(stripped):
            body = _DECORATION.sub("", stripped).strip()
            if body and not _NOTE_PREFIX.match(body) and not _SECTION_HEADER.match(body):
                removed.append((path, body))
    found: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    # moved text counts as kept anywhere in the change (a function moved to another module keeps its docstring)
    blob = " ".join(t for texts in added.values() for t in texts if t)
    for file, body in removed:
        key = (file, " ".join(body.split()))
        if key in seen or _plain(body) in blob:
            continue
        seen.add(key)
        found.append({"file": _clean(file, 200), "text": _clean(body, 160)})
        if len(found) >= 8:
            break
    return found


def assess(objective: str, tests: dict[str, str], *, verdict: str, freshness: str,
           exercise: dict[str, Any] | None, diff: str = "", base_source=None) -> dict[str, Any]:
    rows = requirements(objective, tests) if tests else []
    erased = removed_requirement_text(diff, base_source) if diff else []
    notes: list[str] = ["repo-ai does not certify that the task is correct; it reports what the frozen tests observed"]
    for item in erased:  # first after the disclaimer: the CLI shows only the leading notes
        notes.append(f"the candidate removed documentation that states a requirement ({item['file']}): {item['text']!r}; "
                     "check the behaviour it described is still met (tests passing does not show it)")
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
    return {"schema": SCHEMA, "headline": headline, "task_correct": "CLAIM_UNVERIFIED",
            "unechoed_qualifiers": scoped, "requirements": rows, "removed_requirement_text": erased,
            "notes": [_clean(n, 300) for n in notes]}
