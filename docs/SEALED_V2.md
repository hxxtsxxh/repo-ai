# sealed-v2: a fresh, harder confirmatory benchmark (built in v0.7.6)

**Status:**
- **Used once:** by the exploratory experiment of 2026-10-21 (below).
- **Oracles:** validated in the sandbox.
- **Location:** `benchmarks/sealed-v2/`, in the private repository only. It is
  never shipped in the wheel or the sdist.
- **Authoring notes:** the upstream messages and fix diffs are in
  `benchmarks/authoring/sealed-v2/`. Every agent run is denied them, and the
  integrity audit treats them as protected.

**Used (2026-10-21): no longer untouched.** The exploratory Core-vs-Plain
experiment (`EXPLORATORY-v2-pairs.md`) ran on all 25 tasks. Plain solved 92%,
so the set is near the ceiling, like `final`. It is no longer fresh evidence
for a confirmatory study.

**Why a new set:**
- The v0.7.2 `final` set was analysed in Option A. Changes motivated by those
  results (0.7.6) must be judged on tasks they were not tuned on.
- That set was also near the ceiling: 19 of 24 analysable tasks were solved
  by every arm in every run.

## Tasks

| Project | Licence | Language | Tasks | Architecture exercised |
|---|---|---|---|---|
| sqlglot | MIT | Python | 8 | tokenizer → parser → per-dialect parsers and generators, optimizer |
| dnspython | ISC | Python | 6 | wire parser, rdata types, zone files, message/transfer logic |
| asn1crypto | MIT | Python | 4 | ASN.1 core, x509, cms, csr modules |
| pyasn1 | BSD-2-Clause | Python | 2 | type system, BER and native codecs |
| lark | MIT | Python | 2 | visitors, LALR interactive parser |
| more-itertools | MIT | Python | 1 | numeric_range |
| typing_extensions | PSF-2.0 | Python | 1 | deprecated / class creation |
| marked | MIT | TypeScript (run as JS) | 1 | hooks, instance, lexer/parser selection |

**25 tasks in total.** Each is a re-injected upstream change: the frozen
snapshot with that commit's source change reversed.
- **Hidden tests:** the commit's own test changes (independent upstream tests).
- **Prompt:** written by hand from the authoring notes. It describes symptoms,
  required behaviour and any interface or message the tests check, never the
  fix.
- **Size:** 18 of 25 change two or more source files; the changed source
  lines range from 5 to 147 (median 32).

**Languages:** two. Java, Go and dependency-based JS projects were not
feasible: the offline grading images have no JUnit, no npm packages and no
pytest.

## Selection rule (fixed before any candidate was examined; no hand-picking)

1. Non-merge commits, newest first, within a fixed window per project.
2. At least one package source file and at least one *runnable* test file
   changed.
3. **Harder than v0.7.2:** at least 2 source files, or 1 source file with at
   least 30 changed lines; at most 300 lines and 6 files.
4. The message is not docs, typo, lint, CI, release, bump, format, typing,
   revert, chore or deps only.
5. The fix reverse-applies onto the frozen snapshot.
6. **Sandbox oracle:**
   - buggy state: the visible suite passes and the hidden tests fail;
   - fixed state: the hidden tests pass, and so does the full visible suite
     with them installed.
7. At most 8 tasks per project.

**What was examined:**
- 5,819 commits across 12 projects (9 of them mined). Every commit and its
  rejection reason is in `benchmarks/authoring/sealed-v2/manifest.json`.
- Projects probed but **not used**:
  - pyparsing and mistletoe: their tests need pytest or `parameterized`;
  - docutils: an environment-specific runner;
  - pyelftools: 68 MB of test binaries;
  - pycparser, idna, tornado and zope.interface: 0 tasks met the rule.

**Runnable tests:**
- Test modules that cannot run offline are excluded from a base's visible
  suite and are never hidden tests. That covers optional dependencies, a C
  preprocessor, and one sqlglot module that exceeds the sandbox's 2 GB.
- The lists are in each base's `visible_tests` in `bases.json`.

## Grading

**Success:**
- the hidden upstream tests pass; and
- the base's runnable visible suite passes, with the updated test files
  installed (failures of the hidden tests' own methods are the task, not
  regressions).

**How grading runs:** in the sandbox, on a copy of the workspace without
`__pycache__`.

**What the runner records:**
- `success` covers the hidden tests only.
- `regression` records whether the visible suite failed.
- Success as defined above is `correct_no_regression` in the 0.7.7 report
  (PREREGISTRATION-v2, Amendment 1).

**Why "targeted passes, full fails" happens:**
- sqlglot fixes touch the shared tokenizer, parser or generator, whose
  behaviour all 33 runnable dialect test modules exercise.
- So a change that makes its own dialect's test pass can still fail the task
  by breaking another dialect.

## Limitations

- **Imbalance:** 8 of 25 tasks are sqlglot. The analysis clusters by task, not
  project.
- **Size:** 25 tasks detect only large effects, about 30–38 points at 80%
  power (PREREGISTRATION-v2.md).
- **Contamination:** public projects; memorisation of upstream fixes is
  possible and equal across arms.
- **Language spread:** one TypeScript task cannot support claims about
  JavaScript performance.
