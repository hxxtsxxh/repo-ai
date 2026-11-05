"""Candidate discovery: which capabilities a task might want, before any gate applies constraints.

A port of the research prototype's recommended design ("REC": the v0 vocabulary plus mechanisms and
partial credit). It is deterministic, stdlib only, and runs no process, opens no network connection and
writes no file. The lexicon (`capability_lexicon.json`) is a verbatim copy of the prototype's
`lexicon_v0_mech.json`; the fitted v1 lexicons are never used.

How a task becomes candidates:
1. The task text (at most 2,000 characters) is split into clauses and stemmed.
2. Facets (lexicon concepts) are found as stemmed n-grams. Then:
   - a one-token occurrence inside a longer occurrence of another facet is dropped (longest match);
   - a one-token cue of a guarded facet next to a domain noun is dropped ("score", "label");
   - an occurrence up to three tokens after a negator is dropped ("not about security").
3. Intent rules are conjunctions of facets. A rule fires within one clause (a 12-token window) or across
   two adjacent clauses. A need scores its best rule, plus 0.5 when several rules fire.
4. Only when no rule of a need fires, a multi-facet rule with some facets present gives partial credit
   (at most 1.4). Partial credit can rank a consider-tier candidate, never a recommendation.
5. Disambiguation:
   - installed-state cues without a third-party source are an inventory question, not vetting;
   - a dependency-vulnerability need without code-level cues drops the code-security needs.
6. Repository and file signals only amplify needs the text already supports:
   - a front-end repository raises browser-runtime;
   - a changed manifest raises dependency-vuln;
   - a security-sensitive path raises security-code;
   - a changed test raises verify-change.
   They never create a need. Text work (typos, wording) keeps only strong code needs.
7. The need score decides; a provider's registry weight only ranks providers of that need.
8. Gates filter by facts, not by the task's prohibitions:
   - language scope;
   - semgrep is not offered for a Python-only scope (ruff covers it);
   - browser evidence only for front-end work;
   - docs-only changes.

Constraints the task states ("offline", "don't run anything", "only built-in tools") are reported in a
closed vocabulary and never applied here: the gates module applies them. Detection never removes a need.

The output never contains task text, matched words or file paths: the task is untrusted and agents read
this output. Every string in it is a capability id, a need id, a closed code or a language name.
"""

from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any

SCHEMA = "repo-ai.capability-discovery/1"
FLOOR = 0.6
RECOMMEND_AT = 2.0
MAX_RECOMMEND = 3
MAX_TASK_CHARS = 2000
MAX_CONSTRAINT_CHARS = 8000
MAX_OCCURRENCES = 16  # per facet: bounds the conjunction search on hostile input
MAX_CHANGED = 2000
WINDOW = 12  # tokens: a same-clause conjunction must fit in this span
LEXICON = Path(__file__).with_name("capability_lexicon.json")
KIND_ORDER = {"builtin": 0, "adapter": 1, "external": 2}

# constraint codes: the lexicon's three, plus two written here from general engineering vocabulary
CONSTRAINT_CODES = {"no_exec": "no-exec", "no_network": "no-network", "no_install": "no-install"}
EXTRA_CONSTRAINTS = {
    "static-only": ("static analysis only", "only static analysis", "static checks only", "only static checks",
                    "statically only", "purely static", "static only", "no dynamic analysis",
                    "analyse statically", "analyze statically", "static tools only"),
    "no-third-party": ("no third party", "nothing third party", "without third party", "only built in",
                       "built in only", "builtin only", "only builtin", "only builtins", "no external tools",
                       "without external tools", "only what ships with", "first party only",
                       "only first party", "standard library only", "only the standard library",
                       "stdlib only", "no outside tools"),
}

# --------------------------------------------------------------------------
# context signals. These match the prototype, not capabilities.py: there
# `.html` is a doc extension and `middleware/auth` a security path.
# --------------------------------------------------------------------------
DOC_EXT = {".md", ".mdx", ".rst", ".txt", ".adoc", ".png", ".jpg", ".svg", ".gif"}
FRONTEND_EXT = {".tsx", ".jsx", ".vue", ".svelte", ".css", ".scss", ".sass", ".less", ".html", ".astro"}
FRONTEND_FW = {"react", "next.js", "vue", "nuxt", "svelte", "sveltekit", "angular", "solidjs", "astro",
               "preact", "remix"}
MANIFESTS = {"requirements.txt", "pyproject.toml", "poetry.lock", "uv.lock", "pipfile", "pipfile.lock",
             "package.json", "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "go.mod", "go.sum", "cargo.toml",
             "cargo.lock", "pom.xml", "build.gradle", "build.gradle.kts", "gemfile", "gemfile.lock",
             "composer.json", "composer.lock"}
EXT_LANG = {".py": "Python", ".pyi": "Python", ".js": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
            ".jsx": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript", ".go": "Go", ".rs": "Rust",
            ".java": "Java", ".kt": "Kotlin", ".rb": "Ruby", ".php": "PHP", ".cs": "C#", ".swift": "Swift",
            ".vue": "Vue", ".svelte": "Svelte", ".scala": "Scala", ".c": "C", ".h": "C", ".cpp": "C++"}
SECURITY_PATH = re.compile(r"(?i)(^|[/_.-])(auth\w*|login|logout|session|sessions|crypto\w*|password\w*|secrets?|"
                           r"tokens?|jwt|oauth\w*|permissions?|acl|rbac|security|sanitiz\w*|upload\w*|"
                           r"deseriali\w*)([/_.-]|$)")
TEST_PATH = re.compile(r"(?i)(^|/)(tests?|__tests__|spec)(/|$)|(_test\.go|_test\.py|\.test\.[jt]sx?|"
                       r"\.spec\.[jt]sx?|^test_|/test_)")
CODE_NEEDS = {"verify-change", "blast-radius", "shortlist-files", "review-diff", "security-code",
              "dependency-vuln", "precise-refs", "browser-runtime", "test-adequacy", "property-invariants",
              "security-review-deep"}
DOCS_OK = {"repo-ai.skills-vet", "repo-ai.skills-inventory", "repo-ai.budget"}  # useful on a docs-only change
CODE_LEVEL = ("INJECTION_CLASS", "UNTRUSTED_INPUT", "DANGEROUS_API", "SECRETS_CRYPTO")
PROVIDER = {3: 1.0, 2: 0.85, 1: 0.5}  # registry weight -> share of the need score

Occ = dict[str, list[tuple[int, int, int]]]  # facet -> [(clause, global start, global end)]

# --------------------------------------------------------------------------
# text: normalise, drop stop words, stem (a small suffix stripper, not Porter)
# --------------------------------------------------------------------------
STOP = set("""a an the this that these those my our your its their his her is are was were be been being am
to of for in on at by with and or it i we you me us do does did can could would should will shall may might
please just so some me im ive id also then than there here as from into about if when while very really
want wanna need like get got have has had let lets make sure""".split()) - {"make", "sure", "need"}
_BRIT = re.compile(r"is(e|ed|es|ing|ation|ations)$")
_VOWEL = re.compile(r"[aeiouy]")
_NONWORD = re.compile(r"[^a-z0-9]+")
_APOS = re.compile(r"(\w)'(\w)")
_CLAUSE = re.compile(r"[;?!\n]|\.(?:\s|$)|,\s*but\b|\bbut\b")


@lru_cache(maxsize=8192)
def _stem(w: str) -> str:
    if len(w) == 3 and w.endswith("e") and w.isalpha():
        return w[:-1]
    if len(w) <= 3 or not w.isalpha():
        return w
    if w.endswith(("behaviour", "colour", "behaviours", "colours")):
        w = w.replace("our", "or")
    if len(w) > 5 and _BRIT.search(w):
        w = _BRIT.sub(lambda m: "iz" + m.group(1), w)
    if w.endswith("ies") and len(w) > 4:
        w = w[:-3] + "y"
    elif w.endswith("sses"):
        w = w[:-2]
    elif w.endswith("s") and not w.endswith(("ss", "us", "is")):
        w = w[:-1]
    for suf, rep in (("izations", "iz"), ("ization", "iz"), ("ation", "at"), ("tion", "t"), ("sion", "s")):
        if w.endswith(suf) and len(w) - len(suf) >= 3:
            w = w[: -len(suf)] + rep
            break
    for suf in ("ing", "ed"):
        if w.endswith(suf) and len(w) - len(suf) >= 2 and _VOWEL.search(w[: -len(suf)]):
            w = w[: -len(suf)]
            if len(w) > 2 and w[-1] == w[-2] and w[-1] not in "lsz" and w[-1] not in "aeiou":
                w = w[:-1]
            break
    if w.endswith("e") and len(w) >= 3:
        w = w[:-1]
    return w


def _raw_toks(text: str) -> list[str]:
    t = text.lower().replace("’", "'").replace("`", " ")
    t = _APOS.sub(r"\1\2", t)  # don't -> dont
    return [w for w in _NONWORD.sub(" ", t).split() if w not in STOP]


def _toks(text: str) -> list[str]:
    return [_stem(w) for w in _raw_toks(text)]


def _clauses(text: str) -> list[tuple[list[str], list[str]]]:
    """(stemmed, raw) tokens per non-empty clause."""
    out = []
    for c in _CLAUSE.split(text):
        raw = _raw_toks(c)
        if raw:
            out.append(([_stem(w) for w in raw], raw))
    return out


def _find(seq: list[str], pat: tuple[str, ...]) -> bool:
    n = len(pat)
    return bool(n) and any(tuple(seq[i:i + n]) == pat for i in range(len(seq) - n + 1))


# --------------------------------------------------------------------------
# lexicon, compiled once
# --------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _lexicon_bytes() -> bytes:
    # line endings normalised: a Windows checkout may convert them, and the hash must not change
    return LEXICON.read_bytes().replace(b"\r\n", b"\n")


def lexicon_sha256() -> str:
    return hashlib.sha256(_lexicon_bytes()).hexdigest()


@lru_cache(maxsize=1)
def _compiled() -> dict[str, Any]:
    lex = json.loads(_lexicon_bytes().decode("utf-8"))
    # a form starting with "=" matches unstemmed words; any other form matches stems
    raw: dict[str, list[tuple[str, str, tuple[str, ...]]]] = {}
    owner: dict[tuple[str, ...], set[str]] = {}
    for c, forms in lex["concepts"].items():
        lst = []
        for f in forms:
            kind, t = ("raw", tuple(_raw_toks(f[1:]))) if f.startswith("=") else ("stem", tuple(_toks(f)))
            lst.append((f, kind, t))
            owner.setdefault(t, set()).add(c)
        raw[c] = lst
    # forms indexed by first token; a multi-word form that loses words to stop-word removal is dropped
    # when it collapses onto another concept's form or onto one token ("really test" -> "test")
    index: dict[str, dict[str, list[tuple[str, tuple[str, ...]]]]] = {"raw": {}, "stem": {}}
    for c, fs in raw.items():
        for f, kind, t in fs:
            collapsed = len(t) < len(f.lstrip("=").split())
            if not t or (collapsed and owner[t] - {c}) or (collapsed and len(t) < 2):
                continue
            index[kind].setdefault(t[0], []).append((c, t))
    return {
        "index": index,
        "trivial": [tuple(_toks(f)) for f in lex["trivial"]],
        "constraints": {CONSTRAINT_CODES[k]: [tuple(_toks(f)) for f in v] for k, v in lex["constraints"].items()},
        "extra": {k: [tuple(_toks(f)) for f in v] for k, v in EXTRA_CONSTRAINTS.items()},
        "negators": [tuple(_toks(f)) for f in lex["negators"]],
        "intents": lex["intents"],
        "guarded": set(lex.get("guarded", [])),
    }


# --------------------------------------------------------------------------
# facets and intents
# --------------------------------------------------------------------------
def _occurrences(cls: list[tuple[list[str], list[str]]], lx: dict[str, Any]) -> Occ:
    found: dict[str, set[tuple[int, int, int]]] = {}
    base = 0
    for ci, (seq, rawseq) in enumerate(cls):
        negend = [i + len(n) for n in lx["negators"] for i in range(len(seq) - len(n) + 1)
                  if n and tuple(seq[i:i + len(n)]) == n]
        for kind, toks in (("stem", seq), ("raw", rawseq)):
            idx = lx["index"][kind]
            for i, w in enumerate(toks):
                for c, f in idx.get(w, ()):
                    if tuple(toks[i:i + len(f)]) != f or any(0 <= i - e <= 3 for e in negend):
                        continue
                    found.setdefault(c, set()).add((ci, base + i, base + i + len(f) - 1))
        base += len(seq) + 50  # clause gap: adjacency is judged by clause index, not position
    occ = {c: sorted(v) for c, v in found.items()}
    # longest match: a one-token occurrence inside another facet's longer occurrence is not a cue
    longer = [(c, o) for c, os in occ.items() for o in os if o[2] > o[1]]
    for c in occ:
        occ[c] = [o for o in occ[c]
                  if not (o[1] == o[2] and any(c2 != c and lo[1] <= o[1] <= lo[2] for c2, lo in longer))]
    # polysemy guard: "score", "label", "pool" next to a one-token cue make it a domain word
    dn = {p for o in occ.get("DOMAIN_NOUN", []) for p in (o[1], o[2])}
    for c in lx["guarded"] & set(occ):
        occ[c] = [o for o in occ[c] if not (o[1] == o[2] and (o[1] - 1 in dn or o[1] + 1 in dn))]
    return {c: v[:MAX_OCCURRENCES] for c, v in occ.items() if v}


def _alts(el: Any) -> list[str]:
    return [el] if isinstance(el, str) else list(el)


def _fires(elements: list[Any], occ: Occ) -> bool:
    """Every facet present, within one clause (a WINDOW-token span) or across two adjacent clauses."""
    lists = []
    for el in elements:
        o = [x for a in _alts(el) for x in occ.get(a, [])]
        if not o:
            return False
        lists.append(o)
    if len(lists) == 1:
        return True
    # two adjacent clauses k, k+1: each facet has an occurrence in one of them and both are used
    clause_sets = [{x[0] for x in o} for o in lists]
    for k in sorted(set().union(*clause_sets)):
        pair = [s & {k, k + 1} for s in clause_sets]
        if all(pair) and not all(p == {k} for p in pair) and not all(p == {k + 1} for p in pair):
            return True
    # one clause: some occurrence start `lo` such that every facet has an occurrence in [lo, lo + WINDOW]
    for ci in set.intersection(*clause_sets):
        same = [[x for x in o if x[0] == ci] for o in lists]
        for lo in sorted({x[1] for s in same for x in s}):
            if all(any(x[1] >= lo and x[2] <= lo + WINDOW for x in s) for s in same):
                return True
    return False


def _constraints(cls: list[Any], lx: dict[str, Any]) -> set[str]:
    flat = [t for seq, _ in cls for t in seq]
    found = {code for code, fs in lx["constraints"].items() if any(_find(flat, f) for f in fs)}
    return found | {code for code, fs in lx["extra"].items() if any(_find(seq, f) for seq, _ in cls for f in fs)}


def _analyse(task: str, lx: dict[str, Any]) -> dict[str, Any]:
    cls = _clauses(task)
    occ = _occurrences(cls, lx)
    constraints = _constraints(cls, lx)
    flat = [t for seq, _ in cls for t in seq]
    needs: dict[str, float] = {}
    partial: set[str] = set()
    for need, rules in lx["intents"].items():
        fired = [w for elements, w in rules if _fires(elements, occ)]
        if fired:
            top = max(fired)
            needs[need] = top + (0.5 if len(fired) > 1 and top >= 2 else 0.0)
            continue
        # soft conjunction: a multi-facet rule with some facets present is shortlist-only evidence
        part = 0.0
        for elements, w in rules:
            if len(elements) > 1:
                have = sum(1 for el in elements if any(occ.get(a) for a in _alts(el)))
                if have:
                    part = max(part, 0.5 * w * have / len(elements))
        if part:
            needs[need] = round(min(part, 1.4), 2)
            partial.add(need)
    # installed-state cues without a third-party source: an inventory question, not vetting
    if needs.get("audit-installed", 0) >= 2.5 and not occ.get("THIRDPARTY") and "vet-third-party" in needs:
        needs["vet-third-party"] = min(needs["vet-third-party"], 1.5)
    if (needs.get("vet-third-party", 0) >= 3 and occ.get("THIRDPARTY") and not occ.get("INSTALLED")
            and "audit-installed" in needs):
        needs["audit-installed"] = min(needs["audit-installed"], 1.5)
    return {"needs": needs, "partial": partial, "occ": occ, "constraints": constraints,
            "trivial": any(_find(flat, f) for f in lx["trivial"])}


# --------------------------------------------------------------------------
# repository and change signals
# --------------------------------------------------------------------------
def _file_signals(changed: list[str]) -> dict[str, Any]:
    exts = [PurePosixPath(p).suffix.lower() for p in changed]
    names = [PurePosixPath(p).name.lower() for p in changed]
    code = [p for p, e in zip(changed, exts, strict=True) if e in EXT_LANG]
    manifests = sorted({n for n in names if n in MANIFESTS})
    return {
        "languages": sorted({EXT_LANG[e] for e in exts if e in EXT_LANG}),
        # a manifest is not a doc, even requirements.txt
        "docs_only": bool(changed) and not manifests
        and all(e in DOC_EXT or p.startswith("docs/") for p, e in zip(changed, exts, strict=True)),
        "frontend": any(e in FRONTEND_EXT for e in exts),
        "manifests": bool(manifests),
        "security_paths": any(SECURITY_PATH.search(p) for p in code),
        "tests": any(TEST_PATH.search(p) for p in changed),
        "code": bool(code),
    }


def _amplify(needs: dict[str, float], occ: Occ, sig: dict[str, Any], frontend: bool) -> set[str]:
    """Signals raise needs the text already supports, never create one. Returns the needs a file raised."""
    by_file: set[str] = set()
    if frontend and 1.5 < needs.get("browser-runtime", 0) < 3:
        needs["browser-runtime"] += 1.0
    if sig["manifests"] and needs.get("dependency-vuln", 0) >= 2:
        needs["dependency-vuln"] += 1.0
        by_file.add("dependency-vuln")
    if sig["security_paths"] and needs.get("security-code", 0) >= 2:
        needs["security-code"] += 0.5
        by_file.add("security-code")
    if sig["tests"] and needs.get("verify-change", 0) >= 2:
        needs["verify-change"] += 0.5
        by_file.add("verify-change")
    # a dependency question without code-level cues is not a code-security question
    if needs.get("dependency-vuln", 0) >= 3 and not any(occ.get(c) for c in CODE_LEVEL):
        needs.pop("security-code", None)
        needs.pop("security-review-deep", None)
    return by_file


def _cap_scores(needs: dict[str, float], caps: list[dict[str, Any]]) -> dict[str, tuple[float, str]]:
    """The need score decides; the registry weight only ranks providers of that need."""
    out: dict[str, tuple[float, str]] = {}
    for cap in caps:
        weights = (cap.get("needs") or {}).items()
        vals = sorted(((needs.get(n, 0.0) * PROVIDER.get(int(w), 0.5), n) for n, w in weights), reverse=True)
        if vals and vals[0][0] > 0:
            out[cap["id"]] = (round(vals[0][0] + 0.1 * sum(v for v, _ in vals[1:]), 3), vals[0][1])
    return out


def _gate(cap: dict[str, Any], scope: list[str], frontend: bool, docs_only: bool) -> str:
    langs = cap.get("languages") or ["*"]
    if "*" not in langs and scope and not set(langs) & set(scope):
        return "lang"
    if cap["id"] == "adapter.semgrep" and scope and set(scope) <= {"Python"}:
        return "python-only"  # ruff covers a Python-only change without a new install
    if cap["id"] == "ext.browser-evidence" and not frontend:
        return "frontend"
    if docs_only and cap["id"] not in DOCS_OK:
        return "docs-only"
    return ""


def _pick(ranked: list[tuple[str, float, str]], by_id: dict[str, dict[str, Any]], partial: set[str],
          change_langs: list[str]) -> list[str]:
    """At most MAX_RECOMMEND at RECOMMEND_AT or above. One provider per need, unless the second is a
    different kind of evidence or covers a changed-file language the first does not."""
    chosen: list[tuple[str, float, str]] = []
    for cid, s, need in ranked:
        if s < RECOMMEND_AT or need in partial:
            continue
        same = [c for c in chosen if c[2] == need]
        if same and (len(same) >= 2 or by_id[same[0][0]]["kind"] == by_id[cid]["kind"]):
            if not (change_langs and len(same) == 1):
                continue
            covered = set(by_id[same[0][0]].get("languages") or [])
            if "*" in covered or not (set(change_langs) - covered) & set(by_id[cid].get("languages") or []):
                continue
        chosen.append((cid, s, need))
        if len(chosen) == MAX_RECOMMEND:
            break
    return [c[0] for c in chosen]


def _fit(cap: dict[str, Any], need: str, sig: dict[str, Any], scope: list[str], by_file: set[str]) -> list[str]:
    fit = [f"need:{need}"]
    if need in CODE_NEEDS and sig["code"]:
        fit.append("file:code")
    langs = cap.get("languages") or ["*"]
    if "Python" in sig["languages"] and "Python" in langs:
        fit.append("file:python")
    if need == "dependency-vuln" and need in by_file:
        fit.append("file:manifest")
    if need == "browser-runtime" and sig["frontend"]:
        fit.append("file:frontend")
    if need == "security-code" and need in by_file:
        fit.append("file:security-path")
    if "*" not in langs:
        fit += [f"lang:{lang}" for lang in sorted(set(langs) & set(scope))]
    return fit


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------
def discover(task: str, prof: dict[str, Any], changed: list[str] | None, manifest: dict[str, Any]) -> dict[str, Any]:
    """Deterministic: the same inputs give the same answer. No process, network or file write."""
    lx = _compiled()
    full = str(task)[:MAX_CONSTRAINT_CHARS]  # a stated constraint is never cut off with the analysed text
    task = full[:MAX_TASK_CHARS]
    changed = [str(p) for p in (changed or [])][:MAX_CHANGED]
    caps = list(manifest.get("capabilities") or [])
    by_id = {c["id"]: c for c in caps}
    sig = _file_signals(changed)
    scope = sig["languages"] or [str(x) for x in prof.get("languages") or []]
    frontend = sig["frontend"] or bool({str(f).lower() for f in prof.get("frameworks") or []} & FRONTEND_FW)

    a = _analyse(task, lx)
    if len(full) > len(task):
        a["constraints"] = set(a["constraints"]) | _constraints(_clauses(full), lx)
    untrimmed = dict(a["needs"])
    needs = dict(untrimmed)
    if a["trivial"]:  # text work keeps only an explicit, strong code need
        needs = {n: v for n, v in needs.items() if n not in CODE_NEEDS or v >= 3}
    by_file = _amplify(needs, a["occ"], sig, frontend)
    scores = _cap_scores(needs, caps)

    def key(cid: str, s: float) -> tuple[float, int, str]:
        return (-s, KIND_ORDER.get(by_id[cid]["kind"], 9), cid)

    ranked: list[tuple[str, float, str]] = []
    excluded: list[tuple[tuple[float, int, str], str]] = []
    for cid, (s, need) in sorted(scores.items(), key=lambda kv: key(kv[0], kv[1][0])):
        why = _gate(by_id[cid], scope, frontend, sig["docs_only"])
        if not why:
            ranked.append((cid, s, need))
        elif s >= FLOOR:
            excluded.append((key(cid, s), why))
    if a["trivial"]:  # what text work removed, reported once and only when no gate removes it anyway
        _amplify(untrimmed, a["occ"], sig, frontend)
        for cid, (s, _) in _cap_scores(untrimmed, caps).items():
            if s >= FLOOR and scores.get(cid, (0.0, ""))[0] < FLOOR and not _gate(by_id[cid], scope, frontend,
                                                                                   sig["docs_only"]):
                excluded.append((key(cid, s), "trivial"))
    excluded.sort()

    picked = set(_pick(ranked, by_id, a["partial"], sig["languages"]))
    candidates = [{"id": cid, "score": s, "tier": "recommend" if cid in picked else "consider", "need": need,
                   "fit": _fit(by_id[cid], need, sig, scope, by_file)}
                  for cid, s, need in ranked if s >= FLOOR]
    hint = "no-change" if not changed else "docs-only" if sig["docs_only"] else "code-change"
    return {"schema": SCHEMA, "lexicon_sha256": lexicon_sha256(), "candidates": candidates,
            "excluded": [{"id": k[2], "why": why} for k, why in excluded],
            "constraints": sorted(a["constraints"]), "hint": hint, "langs": scope,
            # every record a gate rules out, whatever its score: `--all` must not bring them back
            "gated": sorted({c["id"]: why for c in caps if (why := _gate(c, scope, frontend, sig["docs_only"]))
                             }.items())}
