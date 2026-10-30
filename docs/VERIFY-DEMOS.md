# `repo-ai verify` demonstrations (recorded 2026-10-21)

These are real transcripts on public repositories, recorded on the build in this branch. Long lines are
trimmed. They are kept as recorded. Later builds changed some wording and nothing else:
- `declared (declared in …)` became `declared in …`;
- `MEDIUM: static import evidence only` became "some of the change rests on static evidence only";
- `ran X in N sandboxed process(es)` became `ran X: N sandboxed process(es) in all (…)`;
- the closing "A pass covers…" line now appears only after a passing verdict. The sandbox is macOS seatbelt, running the host interpreter.

In this host environment Python-Markdown is not *installed*, so its entry-point lookups
fail: test files that use extensions by name already fail at the base. The demo shows how
`verify` separates those failures from the ones the change introduces.

## 1. Python-Markdown: a module that static imports cannot fully see

`markdown/extensions/toc.py` is registered as an entry point and loaded by a computed name
(`importlib.import_module(ext_name)`). The change stops `slugify` lowercasing.

```text
 markdown/extensions/toc.py | 2 +-
 1 file changed, 1 insertion(+), 1 deletion(-)
$ repo-ai verify            # no runtime evidence yet
repo-ai verify: 1 changed file against HEAD

changed
  markdown/extensions/toc.py  [source, modified, units: slugify]
      ! entry point markdown.extensions:toc in pyproject.toml
      evidence: 4 linked test file(s); runtime evidence none

selected 4 of 32 test files
  tests/test_apis.py  [string-reference] reaches markdown/extensions/toc.py
  tests/test_legacy.py  [string-reference] reaches markdown/extensions/toc.py
  tests/test_syntax/extensions/test_smarty.py  [string-reference] reaches markdown/extensions/toc.py
  tests/test_syntax/extensions/test_toc.py  [string-reference] reaches markdown/extensions/toc.py

confidence: LOW: the selection may miss tests; run the full suite
  - markdown/extensions/toc.py may be loaded by a computed name (entry point markdown.extensions:toc in pyproject.toml); static imports cannot list...
uncertainty
  - no runtime evidence: selection rests on static imports only (`repo-ai verify --record` records which code each test executes)

run
  targeted:   python -m unittest tests.test_apis tests.test_legacy tests.test_syntax.extensions.test_smarty tests.test_syntax.extensions.test_toc
  full suite: python -m unittest discover -s tests -t .   <- required
  sandboxed:  repo-ai verify --run
$ repo-ai verify --record
recorded runtime evidence for 32 test file(s); 15 already failing: tests/test_apis.py, tests/test_extensions.py, tests/test_legacy.py, tests/test_s...
$ repo-ai verify
repo-ai verify: 1 changed file against HEAD

changed
  markdown/extensions/toc.py  [source, modified, units: slugify]
      ! entry point markdown.extensions:toc in pyproject.toml
      evidence: 4 linked test file(s); runtime evidence fresh

selected 4 of 32 test files   (est. 7.6s of 57.7s, 13% of suite time)
  tests/test_syntax/extensions/test_toc.py  [runtime] executed changed slugify (+1 more)
  tests/test_syntax/extensions/test_smarty.py  [string-reference] reaches markdown/extensions/toc.py
  tests/test_apis.py  [string-reference] reaches markdown/extensions/toc.py
  tests/test_legacy.py  [string-reference] reaches markdown/extensions/toc.py

confidence: HIGH: every changed code unit has fresh runtime evidence
uncertainty
  - 15 test file(s) already failed when evidence was recorded: tests/test_apis.py, tests/test_extensions.py, tests/test_legacy.py, tests/test_synta...

run
  targeted:   python -m unittest tests.test_syntax.extensions.test_toc tests.test_syntax.extensions.test_smarty tests.test_apis tests.test_legacy
  full suite: python -m unittest discover -s tests -t .   (before merging)
  sandboxed:  repo-ai verify --run   (--full adds the full suite)
$ repo-ai verify --run
verification evidence 2026-10-21T17:29:38  (seatbelt sandbox)
applies to the current working tree
verdict: regression
selected test files: 0/4 passed (confidence was high)
  FAIL    tests/test_syntax/extensions/test_toc.py: new failures: 6 test(s) fail with this change that pass at the base (the file already had other...
          new: tests.test_syntax.extensions.test_toc.TestTOC.testTOCWithCustomClass
          new: tests.test_syntax.extensions.test_toc.TestTOC.testTOCWithCustomClasses
          new: tests.test_syntax.extensions.test_toc.TestTOC.testTOCWithCustomTitleClass
          new: tests.test_syntax.extensions.test_toc.TestTOC.testTOCWithEmptyTitleClass
          new: tests.test_syntax.extensions.test_toc.TestTOC.testTocInHeaders
          linked by runtime: executed changed slugify
          linked by string-reference: reaches markdown/extensions/toc.py
          | AssertionError: '<div[60 chars]ef="#Header">Header</a></li>\n</ul>\n</div>\n<[22 chars]/h1>' != '<div[60 chars]ef="#header">Header</a><...
          | FAIL: testTOCWithEmptyTitleClass (tests.test_syntax.extensions.test_toc.TestTOC.testTOCWithEmptyTitleClass)
          | AssertionError: '<div[44 chars]ef="#Header">Header</a></li>\n</ul>\n</div>\n<[22 chars]/h1>' != '<div[44 chars]ef="#header">Header</a><...
          | FAIL: testTocInHeaders (tests.test_syntax.extensions.test_toc.TestTOC.testTocInHeaders)
          | AssertionError: '<div[30 chars]ef="#TOC">[TOC]</a></li>\n</ul>\n</div>\n<h1 i[14 chars]/h1>' != '<div[30 chars]ef="#toc">[TOC]</a></li>...
          | FAIL: testUniqueIds (tests.test_syntax.extensions.test_toc.TestTOC.testUniqueIds)
  FAIL    tests/test_syntax/extensions/test_smarty.py: already failing at the base (the same tests fail)
          linked by string-reference: reaches markdown/extensions/toc.py
          | ERROR: test_angled_quotes (tests.test_syntax.extensions.test_smarty.TestSmartyAngledQuotes.test_angled_quotes)
          | ModuleNotFoundError: No module named 'smarty'
          | ERROR: test_custom_substitutions (tests.test_syntax.extensions.test_smarty.TestSmartyCustomSubstitutions.test_custom_substitutions)
          | ModuleNotFoundError: No module named 'smarty'
          | Ran 11 tests in 0.024s
          | FAILED (errors=11)
  FAIL    tests/test_apis.py: already failing at the base (the same tests fail)
          linked by string-reference: reaches markdown/extensions/toc.py
          | ERROR: testEntryPointExtension (tests.test_apis.TestMarkdownBasics.testEntryPointExtension)
          | ModuleNotFoundError: No module named 'footnotes'
          | Ran 89 tests in 0.031s
          | FAILED (errors=1)
  FAIL    tests/test_legacy.py: already failing at the base (the same tests fail)
          linked by string-reference: reaches markdown/extensions/toc.py
          | ERROR: test_raw_html (tests.test_legacy.TestExtensionsExtra.test_raw_html)
          | ModuleNotFoundError: No module named 'extra'
          | ERROR: test_simple_def_lists (tests.test_legacy.TestExtensionsExtra.test_simple_def_lists)
          | ModuleNotFoundError: No module named 'def_list'
          | Ran 146 tests in 0.103s
          | FAILED (errors=23, skipped=47)
full suite: not run
a pass covers the tests that ran; it is not proof the change is correct
$ git status --porcelain
 M markdown/extensions/toc.py
?? .repo-ai/run/
```

What it shows:
1. **Without runtime evidence**, the plan reports the dynamic-loading blind spot and says
   **LOW: run the full suite**. repo-ai 0.7.7 reported `risk: low` for this kind of change
   while missing 12 of 13 failing cases.
2. **After `--record`**, the runtime evidence shows exactly which test executed `slugify`:
   confidence high, 13% of suite time.
3. **`--run`** separates **6 new failing tests** in `test_toc.py` from failures already present
   at the base (missing entry-point metadata in this environment).

The trailing `?? .repo-ai/run/` line was a defect: the run directory lacked its ignore file
when only `--run` created it. It is fixed in a later commit on this branch.

## 2. webidl-conversions (JavaScript, node:test, V8 coverage)

```text
$ repo-ai verify --record
recorded runtime evidence for 10 test file(s)
40:function integerPart(n) {
 lib/index.js | 1 +
 1 file changed, 1 insertion(+)
$ repo-ai verify
repo-ai verify: 1 changed file against HEAD

changed
  lib/index.js  [source, modified]
      evidence: 1 linked test file(s); runtime evidence fresh

selected 1 of 10 test files   (est. 0.3s of 2.7s, 10% of suite time)
  test/integer-types.js  [runtime] executed changed integerPart (+1 more)

confidence: HIGH: every changed code unit has fresh runtime evidence
uncertainty
  - the repository index was built at e105c6c, not at the base 928446c1afa4; run `repo-ai update` for an exact static graph

run
  targeted:   node --test test/integer-types.js
  full suite: node --test   (before merging)
  sandboxed:  repo-ai verify --run   (--full adds the full suite)
$ repo-ai verify --run
verification evidence 2026-10-21T16:47:49  (seatbelt sandbox)
applies to the current working tree
verdict: regression
selected test files: 0/1 passed (confidence was high)
  FAIL    test/integer-types.js: new failure: passes at the base, fails with this change
          linked by runtime: executed changed integerPart
          linked by static: imports lib/index.js
          |   TypeError: Value is outside the accepted range of -9007199254740991 to 9007199254740991, inclusive.
          | ✖ should return -4294967296 for -4294967296 with [EnforceRange] (0.044625ms)
          | ✖ should return -9007199254740991 for -9007199254740991 with [EnforceRange] (0.041292ms)
          | ✖ should return 9007199254740991 for 9007199254740991 (0.065583ms)
          | ✖ should return 9007199254740991 for 9007199254740991 with [EnforceRange] (0.041166ms)
          |   TypeError: Value is outside the accepted range of 0 to 9007199254740991, inclusive.
full suite: not run
a pass covers the tests that ran; it is not proof the change is correct
$ git status --porcelain   # nothing but the change itself
 M lib/index.js
```

One of 10 test files is selected (10% of suite time), because V8 coverage shows only
`test/integer-types.js` executes `integerPart`. The new failure is confirmed against the base,
and the working tree holds nothing but the change.

## 3. The completion gate and evidence that goes stale

```text
$ repo-ai verify --record
recorded runtime evidence for 2 test file(s)

# the agent ends its turn with an unverified change (Stop hook):
$ echo {} | repo-ai verify --gate
{"decision": "block", "reason": "repo-ai: the current change to calc/core.py has no verification evidence. Run `repo-ai verify --run` to execute th...
$ echo {} | repo-ai verify --gate      # same change again
(silent: once per change)

$ repo-ai verify
repo-ai verify: 1 changed file against HEAD

changed
  calc/core.py  [source, modified, units: scale]
      evidence: 1 linked test file(s); runtime evidence fresh

selected 1 of 2 test files   (est. 0.9s of 1.7s, 51% of suite time)
  tests/test_scale.py  [runtime] executed changed scale (+1 more)

confidence: HIGH: every changed code unit has fresh runtime evidence

run
  targeted:   python -m unittest tests.test_scale
  full suite: python -m unittest discover -s tests -t .   (before merging)
  sandboxed:  repo-ai verify --run   (--full adds the full suite)
$ repo-ai verify --run
verification evidence 2026-10-21T15:32:08  (seatbelt sandbox)
applies to the current working tree
verdict: regression
selected test files: 0/1 passed (confidence was high)
  FAIL    tests/test_scale.py: new failure: passes at the base, fails with this change
          linked by runtime: executed changed scale
          linked by static: imports calc/__init__.py -> calc/core.py
          | FAIL: test_scale (tests.test_scale.T.test_scale)
          | AssertionError: 6 != 4
          | Ran 1 test in 0.000s
          | FAILED (failures=1)
full suite: not run
a pass covers the tests that ran; it is not proof the change is correct
$ repo-ai evidence
exit 0 (0 = evidence covers the working tree)
# the change is edited again: the earlier evidence no longer applies
$ repo-ai evidence
verification evidence 2026-10-21T15:32:08  (seatbelt sandbox)
STALE: the working tree changed after this run; it does not cover the current change
exit 2
```

The gate blocks an unverified change **once**, then stays silent. Evidence covers only the
exact working tree it was recorded for.


---

## 2026-10-22: the hardened workflow, end to end

**Setup:**
- A fresh clone of cachetools, a src-layout project from the dev set, on the
  engine in PR #23 after the production-hardening work.
- macOS seatbelt sandbox, CPython 3.12.
- An uncommitted edit (`maxsize < 0` → `maxsize < -1`) and an untracked
  `.env.local` beside the code.
- Recorded verbatim, then abridged where marked.

**What it shows:**
- **Zero configuration:** the test command is inferred, with `PYTHONPATH=src`
  added and the reason stated.
- **Isolation:** the run happens in a disposable copy, with `.env.local`
  withheld from it. Every failure is re-checked at the base and classified as
  new.
- **The source tree is byte-identical before and after** (the digest lines).
- **Evidence status:** `repo-ai evidence` reports *current*, then *stale* once
  the code changes (exit 2).
- **Runtime evidence** raises confidence to high.
- **Cancellation:** SIGTERM kills the running test and deletes the copies,
  and the tree is unchanged.

**The script:** `digest` is a SHA-256 over every working-tree file plus
`.git/HEAD` and `.git/index`.

```text







# 1. index once (no agent needed)

$ repo-ai init --agent none -q
[exit 0]
# a developer edits a function (uncommitted), and keeps a local secret beside the code
 src/cachetools/__init__.py | 2 +-
 1 file changed, 1 insertion(+), 1 deletion(-)
source tree digest before: 1bdbcdc80d9e0375
# 2-3. what changed, what can catch it, how sure (read-only; the test command is established without configuration)

$ repo-ai verify
repo-ai verify: 1 changed file against HEAD

changed
  src/cachetools/__init__.py  [source, modified, units: __init__]
      evidence: 13 linked test file(s); runtime evidence none

selected 13 of 13 test files
  tests/test_cache.py  [static] imports src/cachetools/__init__.py
  tests/test_cached.py  [static] imports src/cachetools/__init__.py
  tests/test_cachedmethod.py  [static] imports src/cachetools/__init__.py
  tests/test_classmethod.py  [static] imports src/cachetools/__init__.py
  tests/test_fifo.py  [static] imports src/cachetools/__init__.py
  tests/test_func.py  [static] imports src/cachetools/func.py
  tests/test_keys.py  [static] imports src/cachetools/keys.py
  tests/test_lfu.py  [static] imports src/cachetools/__init__.py
  tests/test_lru.py  [static] imports src/cachetools/__init__.py
  tests/test_rr.py  [static] imports src/cachetools/__init__.py
  tests/test_threading.py  [static] imports src/cachetools/__init__.py
  tests/test_tlru.py  [static] imports src/cachetools/__init__.py
  tests/test_ttl.py  [static] imports src/cachetools/__init__.py

confidence: MEDIUM: static import evidence only
uncertainty
  - no runtime evidence: selection rests on static imports only (`repo-ai verify --record` records which code each test executes)
  - 1 untracked credential-like file(s) (.env.local) are not part of the verified change: they are never copied where tests run

test command: python -m unittest discover -s tests -t .   (inferred from the test files)
  - PYTHONPATH=src: the tests import cachetools, which lives only under src/
  - environment: PYTHONPATH=src

run
  targeted:   PYTHONPATH=src python -m unittest tests.test_cache tests.test_cached tests.test_cachedmethod tests.test_classmethod tests.test_fifo tests.test_func tests.test_keys tests.test_lfu tests.test_lru tests.test_rr tests.test_threading tests.test_tlru tests.test_ttl
  full suite: PYTHONPATH=src python -m unittest discover -s tests -t .   (before merging)
  sandboxed:  repo-ai verify --run   (--full adds the full suite)
              tests run in a disposable copy of the working tree, never in it; failures are re-checked against the base
  sharper:    repo-ai verify --record   (once: records which code each test runs)

evidence: none yet for this repository
[exit 0]
# 4-5. run it: sandboxed, in a disposable copy

$ repo-ai verify --run
running 13 selected test file(s) in the seatbelt sandbox, in a disposable copy of the working tree…
  command: python -m unittest discover -s tests -t .  [inferred from the test files]
  isolated copy: 44 files (clone, 0.1s); withheld 1 credential-like untracked file(s)
  fail    batch of 4 file(s): re-running them one by one, each in a fresh copy
  fail    batch of 3 file(s): re-running them one by one, each in a fresh copy
  fail    batch of 3 file(s): re-running them one by one, each in a fresh copy
  pass    batch of 3 file(s) (0.2s)
  fail    tests/test_cache.py (0.1s)
  pass    tests/test_classmethod.py (0.1s)
  pass    tests/test_cached.py (0.1s)
  fail    tests/test_fifo.py (0.1s)
  fail    tests/test_lfu.py (0.1s)
  pass    tests/test_func.py (0.1s)
  fail    tests/test_lru.py (0.1s)
  fail    tests/test_tlru.py (0.1s)
  fail    tests/test_rr.py (0.1s)
  fail    tests/test_ttl.py (0.1s)
  checking failures against the base revision…
  … (the plan above, printed again) …
verification evidence 2026-10-22T02:32:26  (seatbelt sandbox)
applies to the current working tree
verdict: regression
selected test files: 6/13 passed (confidence was medium)
  FAIL    tests/test_cache.py: new failure: passes at the base, fails with this change
          linked by static: imports src/cachetools/__init__.py
          | FAIL: test_maxsize_negative (tests.test_cache.CacheTest.test_maxsize_negative)
          | AssertionError: ValueError not raised
          | Ran 23 tests in 0.004s
          | FAILED (failures=1)
  FAIL    tests/test_fifo.py: new failure: passes at the base, fails with this change
          linked by static: imports src/cachetools/__init__.py
          | FAIL: test_maxsize_negative (tests.test_fifo.FIFOCacheTest.test_maxsize_negative)
          | FAILED (failures=1)
  FAIL    tests/test_lru.py: new failure: passes at the base, fails with this change
          linked by static: imports src/cachetools/__init__.py
          | FAIL: test_maxsize_negative (tests.test_lru.LRUCacheTest.test_maxsize_negative)
          | FAILED (failures=1)
  FAIL    tests/test_ttl.py: new failure: passes at the base, fails with this change
          linked by static: imports src/cachetools/__init__.py
          | FAIL: test_maxsize_negative (tests.test_ttl.TTLCacheTest.test_maxsize_negative)
          | FAILED (failures=1)
  FAIL    tests/test_rr.py: new failure: passes at the base, fails with this change
          linked by static: imports src/cachetools/__init__.py
          | FAIL: test_maxsize_negative (tests.test_rr.RRCacheTest.test_maxsize_negative)
          | FAILED (failures=1)
  FAIL    tests/test_lfu.py: new failure: passes at the base, fails with this change
          linked by static: imports src/cachetools/__init__.py
          | FAIL: test_maxsize_negative (tests.test_lfu.LFUCacheTest.test_maxsize_negative)
          | FAILED (failures=1)
  FAIL    tests/test_tlru.py: new failure: passes at the base, fails with this change
          linked by static: imports src/cachetools/__init__.py
          | FAIL: test_maxsize_negative (tests.test_tlru.TLRUCacheTest.test_maxsize_negative)
          | FAILED (failures=1)
full suite: not run
a pass covers the tests that ran; it is not proof the change is correct
[exit 1]
source tree digest after:  1bdbcdc80d9e0375
 M src/cachetools/__init__.py
?? .env.local
# 6. does the evidence still cover the working tree?

$ repo-ai evidence
verification evidence 2026-10-22T02:32:26  (seatbelt sandbox)
applies to the current working tree
verdict: regression
selected test files: 6/13 passed (confidence was medium)
  FAIL    tests/test_cache.py: new failure: passes at the base, fails with this change
          linked by static: imports src/cachetools/__init__.py
  FAIL    tests/test_fifo.py: new failure: passes at the base, fails with this change
          linked by static: imports src/cachetools/__init__.py
  FAIL    tests/test_lru.py: new failure: passes at the base, fails with this change
          linked by static: imports src/cachetools/__init__.py
  FAIL    tests/test_ttl.py: new failure: passes at the base, fails with this change
          linked by static: imports src/cachetools/__init__.py
  FAIL    tests/test_rr.py: new failure: passes at the base, fails with this change
          linked by static: imports src/cachetools/__init__.py
  FAIL    tests/test_lfu.py: new failure: passes at the base, fails with this change
          linked by static: imports src/cachetools/__init__.py
  FAIL    tests/test_tlru.py: new failure: passes at the base, fails with this change
          linked by static: imports src/cachetools/__init__.py
full suite: not run
a pass covers the tests that ran; it is not proof the change is correct
[exit 0]
# the developer fixes the bug: the evidence is now stale

$ repo-ai evidence
verification evidence 2026-10-22T02:32:26  (seatbelt sandbox)
STALE: the working tree changed after this run; it does not cover the current change
verdict: regression
selected test files: 6/13 passed (confidence was medium)
  FAIL    tests/test_cache.py: new failure: passes at the base, fails with this change
          linked by static: imports src/cachetools/__init__.py
  FAIL    tests/test_fifo.py: new failure: passes at the base, fails with this change
          linked by static: imports src/cachetools/__init__.py
  FAIL    tests/test_lru.py: new failure: passes at the base, fails with this change
          linked by static: imports src/cachetools/__init__.py
  FAIL    tests/test_ttl.py: new failure: passes at the base, fails with this change
          linked by static: imports src/cachetools/__init__.py
  FAIL    tests/test_rr.py: new failure: passes at the base, fails with this change
          linked by static: imports src/cachetools/__init__.py
  FAIL    tests/test_lfu.py: new failure: passes at the base, fails with this change
          linked by static: imports src/cachetools/__init__.py
  FAIL    tests/test_tlru.py: new failure: passes at the base, fails with this change
          linked by static: imports src/cachetools/__init__.py
full suite: not run
a pass covers the tests that ran; it is not proof the change is correct
[exit 2]
# optional: record which code each test executes (once), then plan again

$ repo-ai verify --record
recording runtime evidence for 13 test file(s) in the seatbelt sandbox, in a disposable copy of the working tree (runs the test suite)…
  command: python -m unittest discover -s tests -t .  [inferred from the test files]
  isolated copy: 44 files (clone, 0.1s); withheld 1 credential-like untracked file(s)
  recorded tests/test_cached.py: pass (0.1s)
  recorded tests/test_classmethod.py: pass (0.1s)
  recorded tests/test_cachedmethod.py: pass (0.2s)
  recorded tests/test_cache.py: pass (0.1s)
  recorded tests/test_fifo.py: pass (0.1s)
  recorded tests/test_func.py: pass (0.1s)
  recorded tests/test_keys.py: pass (0.1s)
  recorded tests/test_lfu.py: pass (0.1s)
  recorded tests/test_lru.py: pass (0.1s)
  recorded tests/test_rr.py: pass (0.1s)
  recorded tests/test_threading.py: pass (0.1s)
  recorded tests/test_tlru.py: pass (0.1s)
  recorded tests/test_ttl.py: pass (0.1s)
recorded runtime evidence for 13 test file(s)
[exit 0]

$ repo-ai verify
repo-ai verify: 1 changed file against HEAD

changed
  src/cachetools/__init__.py  [source, modified, units: __init__]
      evidence: 12 linked test file(s); runtime evidence fresh

selected 12 of 13 test files   (est. 1.5s of 1.6s run file by file, 93%)
  tests/test_fifo.py  [runtime] executed changed __init__ (+1 more)
  tests/test_func.py  [runtime] executed changed __init__ (+1 more)
  tests/test_lru.py  [runtime] executed changed __init__ (+1 more)
  tests/test_cached.py  [runtime] executed changed __init__ (+1 more)
  tests/test_ttl.py  [runtime] executed changed __init__ (+1 more)
  tests/test_threading.py  [runtime] executed changed __init__ (+1 more)
  tests/test_rr.py  [runtime] executed changed __init__ (+1 more)
  tests/test_cache.py  [runtime] executed changed __init__ (+1 more)
  tests/test_lfu.py  [runtime] executed changed __init__ (+1 more)
  tests/test_tlru.py  [runtime] executed changed __init__ (+1 more)
  tests/test_classmethod.py  [runtime] executed changed __init__ (+1 more)
  tests/test_cachedmethod.py  [runtime] executed changed __init__ (+1 more)

confidence: HIGH: every changed code unit has fresh runtime evidence
uncertainty
  - 1 untracked credential-like file(s) (.env.local) are not part of the verified change: they are never copied where tests run

test command: python -m unittest discover -s tests -t .   (inferred from the test files)
  - PYTHONPATH=src: the tests import cachetools, which lives only under src/
  - environment: PYTHONPATH=src

run
  targeted:   PYTHONPATH=src python -m unittest tests.test_fifo tests.test_func tests.test_lru tests.test_cached tests.test_ttl tests.test_threading tests.test_rr tests.test_cache tests.test_lfu tests.test_tlru tests.test_classmethod tests.test_cachedmethod
  full suite: PYTHONPATH=src python -m unittest discover -s tests -t .   (before merging)
  sandboxed:  repo-ai verify --run   (--full adds the full suite)
              tests run in a disposable copy of the working tree, never in it; failures are re-checked against the base

evidence: CURRENT. The last run (2026-10-22T02:32:26) covers exactly this change: regression
[exit 0]
# cancellation: a test that hangs; SIGTERM after 6 seconds (Ctrl-C in a terminal does the same)
[exit 130]

cancelled: stopped 1 running test process(es); the disposable copies were deleted and nothing was recorded
digest before: 958718e1bf8d0787  after: 958718e1bf8d0787
no test process left running
```


## 2026-10-22 (adaptive engine): the workflow from a fresh wheel install

**Setup:**
- **Script:** `benchmarks/verify-eval/demo_adaptive.sh`, on a fresh clone of cachetools (public, MIT).
- **Install:** `repo-ai` installed from the wheel built at `f8b9112` into an
  empty virtualenv.
- **Host:** macOS seatbelt sandbox.

**What it shows:**
- `--record` also times the full suite once.
- `verify --run` chooses the full suite because it is measured to be no
  slower.
- One shared failure across 7 files is reported once.
- An identical second run reuses its evidence in 0.5 s.
- `repo-ai evidence` turns STALE when the tree changes.
- A passing change reads as passing.
- The machine-readable summary is printed for agents.
- The source tree digest is identical before and after.

Recorded verbatim; only the scratch path is shortened.

```text
# 0. index once (no agent needed); record which code each test executes (once; also times the full suite)

$ repo-ai init --agent none -q
[exit 0, 1.2s]

$ repo-ai verify --record
recording runtime evidence for 13 test file(s) in the seatbelt sandbox, in a disposable copy of the working tree (runs the test suite)…
  command: python -m unittest discover -s tests -t .  [inferred from the test files]
  isolated copy: 44 files (clone, 0.0s)
  recorded tests/test_cached.py: pass (0.1s)
  recorded tests/test_cache.py: pass (0.1s)
  recorded tests/test_classmethod.py: pass (0.1s)
  recorded tests/test_cachedmethod.py: pass (0.2s)
  recorded tests/test_fifo.py: pass (0.1s)
  recorded tests/test_func.py: pass (0.1s)
  recorded tests/test_keys.py: pass (0.1s)
  recorded tests/test_lfu.py: pass (0.1s)
  recorded tests/test_lru.py: pass (0.1s)
  recorded tests/test_rr.py: pass (0.1s)
  recorded tests/test_threading.py: pass (0.1s)
  recorded tests/test_tlru.py: pass (0.1s)
  recorded tests/test_ttl.py: pass (0.1s)
  measured the full suite as one process: 0.2s (pass), for choosing how to run later changes
recorded runtime evidence for 13 test file(s)
[exit 0, 1.9s]
# 1. a developer edits a function (uncommitted)
 src/cachetools/__init__.py | 2 +-
 1 file changed, 1 insertion(+), 1 deletion(-)
source tree digest before: c64b8994d8631413
# 2-4. what changed, which tests matter and why, how sure (read-only)

$ repo-ai verify
repo-ai verify: 1 changed file against HEAD

changed
  src/cachetools/__init__.py  [source, modified, units: __init__]
      evidence: 12 linked test file(s); runtime evidence fresh

selected 12 of 13 test files   (est. 1.4s of 1.6s run file by file, 93%)
  tests/test_lfu.py  [runtime] executed changed __init__ (+1 more)
  tests/test_ttl.py  [runtime] executed changed __init__ (+1 more)
  tests/test_fifo.py  [runtime] executed changed __init__ (+1 more)
  tests/test_tlru.py  [runtime] executed changed __init__ (+1 more)
  tests/test_lru.py  [runtime] executed changed __init__ (+1 more)
  tests/test_cached.py  [runtime] executed changed __init__ (+1 more)
  tests/test_func.py  [runtime] executed changed __init__ (+1 more)
  tests/test_rr.py  [runtime] executed changed __init__ (+1 more)
  tests/test_threading.py  [runtime] executed changed __init__ (+1 more)
  tests/test_cache.py  [runtime] executed changed __init__ (+1 more)
  tests/test_classmethod.py  [runtime] executed changed __init__ (+1 more)
  tests/test_cachedmethod.py  [runtime] executed changed __init__ (+1 more)

confidence: HIGH: every changed code unit has fresh runtime evidence

test command: python -m unittest discover -s tests -t .   (inferred from the test files)
  - PYTHONPATH=src: the tests import cachetools, which lives only under src/
  - environment: PYTHONPATH=src

run
  targeted:   PYTHONPATH=src python -m unittest tests.test_lfu tests.test_ttl tests.test_fifo tests.test_tlru tests.test_lru tests.test_cached tests.test_func tests.test_rr tests.test_threading tests.test_cache tests.test_classmethod tests.test_cachedmethod
  full suite: PYTHONPATH=src python -m unittest discover -s tests -t .   (before merging)
  sandboxed:  repo-ai verify --run   (--full runs the full suite instead)
              tests run in a disposable copy of the working tree, never in it; failures are re-checked against the base

evidence: none yet for this repository
[exit 0, 0.4s]
# 5-6. run it: sandboxed, in a disposable copy; new failures vs pre-existing

$ repo-ai verify --run
verifying 12 selected test file(s) in the seatbelt sandbox, in a disposable copy of the working tree…
  command: python -m unittest discover -s tests -t .  [inferred from the test files]
  isolated copy: 44 files (clone, 0.0s)
  strategy: full: the full suite (measured 0.2s as one process) is expected to be no slower than the selection (~0.2s in 4 process(es)); it also runs every other test
  running the full suite: PYTHONPATH=src python -m unittest discover -s tests -t .
  checking failures against the base revision…
repo-ai verify: 1 changed file against HEAD: src/cachetools/__init__.py
selected 12 of 13 test files; confidence HIGH: every changed code unit has fresh runtime evidence
ran the full suite as one process in 1 sandboxed process(es), 0.3s: the full suite (measured 0.2s as one process) is expected to be no slower than the selection (~0.2s in 4 process(es)); it also runs every other test

REGRESSION: this change breaks tests that pass at the base
  NEW  7 test files fail with the same error: AssertionError: ValueError not raised
       tests/test_cache.py, tests/test_fifo.py, tests/test_lfu.py, tests/test_lru.py, tests/test_rr.py, tests/test_tlru.py …
       selected because it executed changed __init__ (runtime evidence)
  5 passed
  source tree unchanged
evidence saved; `repo-ai evidence` shows whether it still covers the working tree.
A pass covers the tests that ran; it is not proof the change is correct.
[exit 1, 1.0s]
source tree digest after:  c64b8994d8631413
# again, nothing changed: the evidence for this exact state is reused

$ repo-ai verify --run
verifying 12 selected test file(s) in the seatbelt sandbox, in a disposable copy of the working tree…
  command: python -m unittest discover -s tests -t .  [inferred from the test files]
  reusing the evidence from 2026-10-22T16:00:42: same change, environment, test command and selection (`--rerun` runs it again)
repo-ai verify: 1 changed file against HEAD: src/cachetools/__init__.py
selected 12 of 13 test files; confidence HIGH: every changed code unit has fresh runtime evidence
reused the evidence from 2026-10-22T16:00:42: same change, environment and selection (`--rerun` runs it again)

REGRESSION: this change breaks tests that pass at the base
  NEW  7 test files fail with the same error: AssertionError: ValueError not raised
       tests/test_cache.py, tests/test_fifo.py, tests/test_lfu.py, tests/test_lru.py, tests/test_rr.py, tests/test_tlru.py …
       selected because it executed changed __init__ (runtime evidence)
  5 passed
  source tree unchanged
evidence reused; `repo-ai evidence` shows whether it still covers the working tree.
A pass covers the tests that ran; it is not proof the change is correct.
[exit 1, 0.5s]
# 7. does the evidence still cover the working tree? (the developer reverts the bug)

$ repo-ai evidence
verification evidence 2026-10-22T16:00:42  (seatbelt sandbox)
applies to the current working tree

REGRESSION: this change breaks tests that pass at the base
  NEW  7 test files fail with the same error: AssertionError: ValueError not raised
       tests/test_cache.py, tests/test_fifo.py, tests/test_lfu.py, tests/test_lru.py, tests/test_rr.py, tests/test_tlru.py …
       selected because it executed changed __init__ (runtime evidence)
  5 passed
  source tree unchanged
A pass covers the tests that ran; it is not proof the change is correct.
[exit 0, 0.3s]

$ repo-ai evidence
verification evidence 2026-10-22T16:00:42  (seatbelt sandbox)
STALE: the working tree changed after this run; it does not cover the current change

REGRESSION: this change breaks tests that pass at the base
  NEW  7 test files fail with the same error: AssertionError: ValueError not raised
       tests/test_cache.py, tests/test_fifo.py, tests/test_lfu.py, tests/test_lru.py, tests/test_rr.py, tests/test_tlru.py …
       selected because it executed changed __init__ (runtime evidence)
  5 passed
  source tree unchanged
A pass covers the tests that ran; it is not proof the change is correct.
[exit 2, 0.2s]
# a passing change: same workflow

$ repo-ai verify --run
verifying 12 selected test file(s) in the seatbelt sandbox, in a disposable copy of the working tree…
  command: python -m unittest discover -s tests -t .  [inferred from the test files]
  isolated copy: 44 files (clone, 0.0s)
  strategy: full: the full suite (measured 0.2s as one process) is expected to be no slower than the selection (~0.2s in 4 process(es)); it also runs every other test
  running the full suite: PYTHONPATH=src python -m unittest discover -s tests -t .
repo-ai verify: 1 changed file against HEAD: src/cachetools/__init__.py
selected 12 of 13 test files; confidence HIGH: every changed code unit has fresh runtime evidence
ran the full suite as one process in 1 sandboxed process(es), 0.2s: the full suite (measured 0.2s as one process) is expected to be no slower than the selection (~0.2s in 4 process(es)); it also runs every other test

PASSED: the full suite passed
  12 passed
  source tree unchanged
evidence saved; `repo-ai evidence` shows whether it still covers the working tree.
A pass covers the tests that ran; it is not proof the change is correct.
[exit 0, 0.9s]
# machine-readable summary for agents
{
 "verdict": "selected-and-full-suite-passed",
 "new_failures": [],
 "pre_existing": [],
 "unconfirmed": [],
 "not_compared": [],
 "passed": 12,
 "no_tests": [],
 "not_run": [],
 "strategy": "full",
 "seconds": 0.23,
 "processes": 1,
 "reused": true,
 "source_tree_unchanged": true
}
```
