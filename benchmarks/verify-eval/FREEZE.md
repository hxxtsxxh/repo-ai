# Engine freeze for the held-out run

- **Engine commit:** `d9695d3` (`repo-ai verify` as evaluated). The held-out run uses this
  code unchanged.
- **Frozen:** 2026-10-21T22:25Z, before any held-out project was set up, run, or scored.
- **Development results at freeze:** `results/dev-score.json` (7 projects, 201 changes, 129
  detected).

Engine changes made while developing on the dev set, each with a regression test in
`tests/test_verify_engine.py`:
1. **Python imports in `src/` layouts** were treated as external packages.
2. **`import markdown`** resolved to `docs/reference/markdown.md` instead of the package.
3. **Node `require("..")`** (a package directory) did not resolve to its package.json entry.
4. **Test-helper classification:** sources that share a top-level package with their tests
   (`pyflakes/` and `pyflakes/test/`) were classified as test helpers.
5. **Fresh runtime evidence is authoritative** for tests with complete records, and
   definition-time insertions count as module or class-body changes.
6. **A test that spawns a child process** has incomplete runtime evidence and falls back to
   static links.
7. **String references and literal loads** are graph edges, followed transitively
   (`python -m pkg.tool` in a subprocess).

**Harness environment rule:** for any project that declares entry points, the sandbox
workspace gets the distribution metadata an install would create. Added for Python-Markdown,
whose extension tests failed at baseline without it. It is a generic rule, not
project-specific.

**Development corpus fix:** the cachetools and tomli test commands gained
`PYTHONPATH=src`. No held-out entry was changed.

# Engine freeze for held-out-3 (PROTOCOL.md, Amendment 2)

- **Engine commit:** `75679e9`. The engine is `src/`, tree `fd6947d9a0a6f723f9c3cbb15f9eeca6e9a9b733`.
- **Frozen:** 2026-10-22T07:57Z.
  - This is before any held-out-3 candidate was searched for, cloned or
    indexed, and before its test configuration was read.
  - `src/` does not change until the first held-out-3 result is committed.
  - Harness, docs and benchmark scripts may change, and each such change is
    listed here.
- **Changes since the held-out-2 engine (`280c03a`), all developed on the dev, held-out and
  held-out-2 projects or on synthetic tests:**
  - the disposable workspace, integrity snapshots, cancellation and the
    per-process copies;
  - zero-config command establishment and per-file runner options;
  - batched execution and bounded batch timeouts;
  - planning overhead (scan cache, toolchain discovery);
  - the missing-node read-scope fix and the sweep race fix;
  - the BOM and computed-loader fixes from held-out-2 (post-hoc there).
- **To be recorded below, before the first held-out-3 measurement:** the
  selected projects, their pinned commits, the reference commands, the image
  digests and any replacements.

## Held-out-3 selection (recorded before any held-out-3 project was indexed or measured)

**Procedure:** the ordered lists and mechanical checks of Amendment 2, run with
`select_heldout3.py`. The raw records are in `results/heldout3/selection-*.json`.

**Python, pytest with third-party test dependencies (quota 4).** Filled in list order:

| Project | Commit | Reference command | Test requirements |
|---|---|---|---|
| itsdangerous | `672971d` | `PYTHONPATH=src python -m pytest tests` | pytest, freezegun |
| humanize | `785e5dc` | `PYTHONPATH=src python -m pytest tests` | the project's `tests` extra |
| parse | `175b52d` | `python -m pytest tests` | `tests/requirements.txt` |
| toolz | `451af60` | `python -m pytest toolz/tests` | pytest, pycodestyle |

All reference commands come from each project's CI or tox configuration.
For toolz, the CI's `--doctest-modules` doctests are outside the per-file
universe, as noted in `corpus.json`.

**Python, standard library only at test time (quota 2): not filled.**
- Every remaining candidate uses pytest.
- jsonschema's suite is `unittest`-based, but it needs four runtime
  dependencies.
- No candidate is added after the fact.

**JavaScript/TypeScript, `node --test` (quota 3, at least one TypeScript):**
- **Clarification:** the first code-search page held 76 of 460 results. All
  10 pages were then fetched with the same query.
- **Amendment 2b:** the ≥300-star filter left two size-eligible projects, and
  both are excluded (below). For this quota only, the threshold is lowered to
  **≥50 stars**, with the same order and the same checks. This was decided
  before any measurement.
- **Excluded, with reasons:**
  - qntm/base65536 and building-sunlight-simulator: fewer than 5 test files;
  - rictic/jsonriver: its tests run only after a TypeScript build
    (`wireit` → `tsc` → `dist/`), which neither the harness nor `verify` performs;
  - hellowind777/hello2cc: a Claude Code plugin whose tests execute its own
    hook and skill code. The mandate forbids executing unreviewed third-party
    skills, even in a container;
  - later candidates without 5 test and 5 source files, or whose `test` script
    needs a build step, or that are agent skill or plugin tooling. Each is
    listed in `results/heldout3/selection-node-50stars.json`.
- **Selected, in order:**

  | Project | Language | Commit |
  |---|---|---|
  | Tauber01/ZENCHE | `.mjs` tests | `52d60af` |
  | fefeding/jmgraph | JS | `3d1849d` |
  | openziti/ziti-sdk-nodejs | JS, native addon | `7f75bda` |

- **Reserves:** FEAScript-core, then PortsWhisper-Rust.
- **TypeScript: not met.** No candidate runs TypeScript tests with
  `node --test` without a build step. ZENCHE's `.ts` files are a website and
  native build configuration, not code under test.

**Vitest control:** 4Catalyzer/found `0769f53`. This is plan-only: `verify`
must report that it cannot split the suite and must require the full suite.
No ground truth is needed.

**Images:**
- Python: built from `python:3.12-slim` plus the requirements above, by
  `harness.py image`. Digests and `pip freeze` output are saved to
  `out/<project>/image.json`, and the digests are copied below before setup.
- jmgraph and ZENCHE: the stock `node:24-slim` image. Their tests import only
  Node built-ins and their own sources.
- ziti-sdk-nodejs: `npm ci --ignore-scripts`. Its native addon is not built,
  and the replacement rule applies at baseline.

**Image digests (built 2026-10-22, before setup):**
- localhost/vev-itsdangerous:h3: `sha256:2ce44794fb5ed50120b7660d4e101df86799ab41e9f57d2e2822a76548039faf` (freezegun==1.5.5, iniconfig==2.3.1, packaging==26.3, pluggy==1.7.0, Pygments==2.21.0, pytest==9.1.1, python-dateutil==3.0.0, six==1.17.0, tzdata==2026.5)
- localhost/vev-humanize:h3: `sha256:8a0141a04f8a1b72aaba1a4d2b2908e3fa631aaf0c0c9fe9045e17fb60b6c674` (coverage==7.16.2, freezegun==1.5.5, iniconfig==2.3.1, packaging==26.3, pluggy==1.7.0, py-cpuinfo2==10.1.1, Pygments==2.21.0, pytest==9.1.1, pytest-benchmark==5.3.0, pytest-cov==7.1.0, python-dateutil==3.0.0, six==1.17.0)
- localhost/vev-parse:h3: `sha256:862862b2af5f53c05aae9ad5d0f7fb5a685bc31b492215489d8bb373e51925ac` (coverage==7.16.2, iniconfig==2.3.1, packaging==26.3, pluggy==1.7.0, Pygments==2.21.0, pytest==9.1.1, pytest-cov==7.1.0, typing_extensions==4.16.0)
- localhost/vev-toolz:h3: `sha256:c373dfd664d62ca4fe1eaec3c74097e850c64a42d808c9df6831ba08dd8b9c1c` (iniconfig==2.3.1, packaging==26.3, pluggy==1.7.0, pycodestyle==2.15.0, Pygments==2.21.0, pytest==9.1.1)
- localhost/vev-ziti-sdk-nodejs:h3: `sha256:ac533c7407edd307fe140130617b7c71fadf3ca3b4bf031a32b1e0a8bde74083` (128 node modules)
- docker.io/library/node:24-slim (ZENCHE, jmgraph): `sha256:156e9bc7a0a267cc6ca77b4283e32b123479342df684ce297455d7b95ff5a6b5`

**Replacement (at setup, before any measurement):** ziti-sdk-nodejs → FEAScript-core
(`63b60bf`, the first reserve).
- **Why:** ziti's reference command reaches only 3 test files, so it fails
  eligibility check 4.
- **FEAScript-core's image:** `localhost/vev-feascript-core:h3`, built with
  `npm ci --ignore-scripts`, digest `sha256:9b0dec2204871c132dcfd09a0a88094eb17800ee0228be03f10ec39824270706`.
- The first build attempt failed because image names must be lowercase. The
  name was corrected before any run.

**Baselines and a second replacement (before any selection was computed):**

| Project | Baseline |
|---|---|
| itsdangerous | 5 of 5 pass |
| parse | 7 of 7 |
| toolz | 12 of 13 |
| ZENCHE | 84 of 84 |
| jmgraph | 5 of 5 |
| FEAScript-core | 8 of 8 |
| humanize | **0 of 6** |

- toolz's one failing file, `test_package.py`, needs installed package
  metadata. It is excluded from scoring by protocol.
- humanize fails because `src/humanize/_version.py` is generated by hatch-vcs
  at build time and is absent from a checkout. Under the replacement rule it is
  replaced by **boltons** (`4e5faa3`), the next Python candidate.
  - Reference command: `python -m pytest tests`, from tox.
  - Image: `localhost/vev-boltons:h3`, digest `sha256:aa352ad631036ff5d098b572aac3096bb62ca433ea2c87093b920371fbbc7a3a`.
  - Baseline: 29 of 29 pass.

**Final held-out-3 set (7 projects):**
- Python (pytest, image dependencies): itsdangerous, parse, toolz, boltons.
- JavaScript (`node --test`): ZENCHE, jmgraph, FEAScript-core (npm
  dependencies).
- Vitest control, plan-only: found.

**Harness change before measurement (not engine):** the isolated `HOME` that
repo-ai runs with now links `~/.config/containers` and
`~/.local/share/containers`, so a `verify --sandbox podman` started by the
harness can reach the podman machine.

# Engine freeze for held-out-4 (PROTOCOL.md, Amendment 3)

- **Engine commit:** `ccb0622`. The engine is `src/`, tree `96fb762383f8dbc5c8a8c71f16b99a00d8c8358c`.
- **Frozen:** 2026-10-22T18:27Z.
  - This is before the held-out-4 candidate search runs, and before any
    candidate is cloned, indexed or has its test configuration read.
  - `src/` does not change until the first held-out-4 results are committed.
  - Harness, docs and benchmark scripts may change, and each such change is
    listed here.
- **Changes since the held-out-3 engine (`75679e9`):**
  - held-out-3's post-hoc selection fix (`a8653bc`);
  - the adaptive engine of this branch: the run shape, per-test reports,
    grouped base comparison, caches and reuse;
  - the development-measurement fixes (`bcfadc6`, `3db45d8`);
  - the Windows reporter fixes (`f93c32d`, `ccb0622`).

  All were developed on the 17 projects of the earlier sets, on synthetic
  tests, or on CI.
- **The previous engine** for the comparison is `cf56523`, installed
  separately.

## Held-out-4 selection (recorded before any held-out-4 project was indexed or measured)

**Procedure:** the ordered lists and mechanical checks of Amendment 3, run
with `select_heldout4.py`. The raw records are in
`results/heldout4/selection*.json`. Test configuration was read one candidate
at a time, in list order, only to apply checks 3–5 and 7.

**Python, pytest with third-party test or runtime dependencies (quota 3):**

| Candidate | Decision |
|---|---|
| tomlkit | **selected** (`eddd27e`): 10 test files, 13 source files, pytest. Reference `python -m pytest -q tests` (CI) |
| python-tabulate | check 4: 4 source files |
| markupsafe | check 4: 2 Python source files and a C extension |
| cattrs | **selected** (`bde101a`): 57 test files, 51 source files. Reference `PYTHONPATH=src python -m pytest tests` (Justfile; `-x --ff -n auto` dropped). Image: the `test` group and every extra the tests import |
| structlog, packaging, wcwidth | check 1: GitHub reports no licence (`NOASSERTION`); applied mechanically |
| jsonschema | check 3: its suite runs with `virtue`, not pytest |
| loguru | **selected** (`bce5dfd`): 50 test files, 19 source files. Reference `python -m pytest tests` (tox; coverage flags dropped). Image: pytest, freezegun, colorama, mypy |

**Python, standard library only at test time (quota 2):**

| Candidate | Decision |
|---|---|
| jmespath.py | **selected** (`2812594`): 6 test files, 8 source files. Reference `python -m pytest tests` (tox). hypothesis is used only by `extra/`, outside `tests/` |
| xmltodict | check 4: 2 test files |
| schedule | check 4: 1 test file |
| python-sortedcontainers | check 1: `NOASSERTION` |
| idna | not standard library only: its test requirements include hypothesis |
| docopt | check 4: 1 test file |
| chardet | **selected** (`88107b4`): 46 test files. Reference `PYTHONPATH=src python -m pytest tests scripts/tests --ignore=tests/test_accuracy.py` (CI; coverage flags dropped). `tests/test_accuracy.py`, which the CI also ignores, is excluded from scoring |

**Replacement (at baseline, before any selection was computed):** chardet →
colorama.
- chardet passes 9 of 52 test files at baseline: `src/chardet/_version.py` is
  generated at build time and absent from a checkout.
- pyparsing, the next candidate, fails the standard-library check: its tests
  import matplotlib, railroad and littletable.
- colorama (`841634e`) is selected: 5 test files, 6 source files, standard
  library only. Reference `python -m unittest discover -p *_test.py` (tox).
  It passes 5 of 5 at baseline.

**Other baselines:**

| Project | Baseline |
|---|---|
| tomlkit | 9 of 10 pass (`tests/test_toml_tests.py` needs the `toml-test` git submodule) |
| cattrs | 53 of 57 (four files for Python 3.14/3.15 features) |
| loguru | 50 of 50 |
| jmespath.py | 6 of 6 |

**JavaScript / TypeScript (Amendment 3b).** The searches returned 228
JavaScript and 853 TypeScript repositories, with no metadata errors; 28 and 64
were eligible by metadata (`results/heldout4/selection-3b.json`). Each root
`test` script was read in star order
(`results/heldout4/selection-3b-test-scripts.json`).

*JavaScript, `node --test` (quota 2):*

| Candidate | Decision |
|---|---|
| BasedHardware/omi, zhongerxin/Cowart | check 3: no root `test` script |
| likec4/likec4, emiliaprotocol/emilia-protocol | check 3: Vitest |
| zts212653/clowder-ai, openfilm/openfilm | check 3: a pnpm workspace script, not `node --test` |
| vibeinging/dsh-desktop | check 3: the test script runs a wrapper script and bootstrap checks |
| brunob/leaflet.fullscreen | check 4: 1 test file |
| gabrielchasukjin/cloi | **selected** (`1da62db`): `node --test test/**/*.test.js`, 18 test files, 52 JavaScript files, npm lockfile. Baseline 18 of 18 |
| Commit451/skyhook | its tests are TypeScript (`.ts`, `--experimental-strip-types`): classified for the TypeScript quota by its test files, not by which search found it |
| xiaojilele-glitch/WhyBuddy | check 3: a chain of five package scripts |
| lyming99/autoplan | **selected** (`0d40ed8`): `node --test src/**/*.test.js`, 71 test files in the universe, npm lockfile. Baseline 44 of 71 (more than half pass) |

*TypeScript through Node's type stripping (quota 1):*
- Every candidate of the TypeScript search fails check 3 or 7, in star order:
  - a build or compile step;
  - Vitest, Jest or Angular;
  - workspace scripts;
  - the third-party loaders `tsx` and `ts-node`;
  - custom runner scripts;
  - mini-yifan/dsh-orb-cordis, an agent-harness plugin (check 7) with a pnpm
    lockfile.
- **Selected: Commit451/skyhook** (`af08d3f`), which the JavaScript search
  found. `node --experimental-strip-types --test test/**/*-spec.ts`, 47 test
  files, 50 source files, an npm lockfile, `engines.node >= 24`. Baseline 47
  of 47.

**Final held-out-4 set (8 projects):**
- Python with dependencies (pytest): tomlkit, cattrs, loguru.
- Python, standard library only: jmespath.py (pytest), colorama (unittest).
- JavaScript (`node --test`): cloi, autoplan.
- TypeScript (`node --test` with type stripping): skyhook.

**Images (built 2026-10-22, before setup):** recorded in `out/<project>/image.json`
and summarised in `results/heldout4/images.json`.

## After the first held-out-4 results (committed in `207eb2d`, `03e9376`, `826143d`)

**Engine changes, each labelled in its commit:**

| Commit | Kind | Motivated by |
|---|---|---|
| `9f150a1` | compatibility | macOS CI runner (Homebrew Node could not start under seatbelt) |
| `8498671` | **post-hoc** | held-out-4 tomlkit (an unattributable full suite decided the verdict of passing changes) |
| `3b57a88` | **post-hoc** | held-out-4 jmespath.py and colorama zero-config (`tox.ini`; nested Makefile variables) |
| `9b877d9` | compatibility | the same macOS CI runner (its Node links OpenSSL 4) |
| `918a4d2` | robustness | the local full test suite under load: a cancelled run's test process survived (cancellation now also reaps every marked process) |
| `c33e4a4` | **post-hoc** | re-measuring `3b57a88` on all five sets: a `tox.ini` pytest command is taken only when the tests import pytest (genshi and supervisor had become runner-not-installed) |

Post-hoc measurements of these are labelled as such in `RESULTS.md`. None is
validated on a fresh set.


# Engine freeze for held-out-5 (PROTOCOL.md, Amendments 4 and 4a)

- **Engine commit:** `2f6ea31`. The engine is `src/`, tree
  `d0060a3fe9a9f1c26f44f0fd30cee77e57d1c62a`. This is the build proposed for
  release (PR #25).
- **Frozen:** 2026-10-23, before the held-out-5 candidate search runs, and
  before any candidate is cloned, indexed or has its test configuration
  read.
  - Amendment 4 was committed in `1a86667` and Amendment 4a in `413458d`,
    both before this freeze.
  - `src/` does not change until the first held-out-5 results are committed.
    A later change is labelled post-hoc and is not validated by this set.
- **Verified on this exact commit before the search:**
  - **The full local suite** (macOS, seatbelt): 650 passed.
  - **CI run `39883135091`:** the lint, test, sandbox, bwrap, benchmark and
    eval-offline jobs passed.
    - The job `test (windows-latest, py3.10)` failed once, in
      `tests/test_graph_packet.py::test_killed_update_leaves_a_recoverable_index`.
      That is the index's recovery after an `update` killed 0.8 s in, a timing
      test of code PR #25 does not touch.
    - It passed on a re-run of that job. It passed 10 of 10 times locally,
      and it passed on Windows 3.13 in the same run.
    - It is recorded as a flaky test outside verify: a follow-up to
      investigate, not a pass of anything verify does.
  - **`test-macos`** is skipped on pull-request events. A `workflow_dispatch`
    run of the full matrix on this commit is listed in `RESULTS.md`.
- **Changes since the held-out-4 engine (`ccb0622`)**, from `git log
  ccb0622..2f6ea31 -- src`:
  - `9f150a1`, `9b877d9`: Homebrew Node under seatbelt (OpenSSL configuration
    read rule), found by CI;
  - `8498671` (POST-HOC on held-out-4): a full suite run only for speed that
    cannot be attributed no longer decides the verdict;
  - `3b57a88`, `c33e4a4` (POST-HOC on held-out-4): zero-config `tox.ini`
    and nested Makefile variables;
  - `918a4d2`: cancellation reaps every process a seatbelt run started;
  - `f8b9112`: the evidence view and the report wording;
  - `0d05caa`: the pre-release audit fixes (`docs/VERIFY-AUDIT-2026-10.md`),
    gate P1/P2 and `verify --paths`;
  - `debe17e`: the guardian (cleanup when `repo-ai` itself is killed);
  - `2f6ea31`: type fixes found by CI's mypy (no behaviour change).

  All were developed on the earlier sets' projects, on synthetic fixtures,
  or on CI. None was developed on a held-out-5 candidate.
- **The previous adaptive engine** for the comparison is `ccb0622` (the
  held-out-4 freeze), installed separately (`frozenenv`).


## Held-out-5 selection (recorded before any held-out-5 project was set up, indexed or measured)

**Procedure:** `select_heldout5.py`, run once on 2026-10-23 after the freeze
above. The raw record is `results/heldout5/selection.json`; every read and
decision, in order, is in `results/heldout5/reads.json`.
- **Check 8:** 1623 repositories named by earlier selection
  records or the corpus, plus the task bases (asn1crypto, bottle, cachetools, dnspython, lark, ledger, markdown, marked, more-itertools, pyasn1, pyflakes, shop, simplejson, sqlglot, tomli, typing-extensions, workspace),
  are excluded. No other reserve list exists in the repository.
- **Searches:**
  - JavaScript `"require('node:test')" language:JavaScript`: 620 repositories, 0 metadata errors,
    48 eligible by metadata.
  - TypeScript `"--experimental-strip-types" filename:package.json`: 765 repositories, 0 metadata errors,
    22 eligible by metadata.
- **Order:** candidates were read one at a time, in list (or star) order, and
  reading stopped when a quota was filled. A candidate whose description
  already showed an agent skill or plugin package (check 7) was not cloned.
- **One rule decided during selection, before the file it applied to was
  read:** a `test` script that is a single `npm run` hop is accepted only if
  it resolves to exactly one `node --test` invocation, with no build step and
  no third-party loader. It was applied once (Gan-Tu/Widgets), and the
  candidate was excluded under it.

*Python with third-party test or runtime dependencies (quota 3):*

| # | Candidate | Decision |
|---|---|---|
| 1 | marshmallow-code/marshmallow (`b762ea2`) | **selected**: runner: pytest (tox: pytest {posargs}); files: 15 test, 14 source; deps: pytest, simplejson from PyPI. Reference `PYTHONPATH=src python -m pytest tests`. |
| 2 | python-attrs/attrs (`ee66e72`) | **selected**: runner: pytest (tox: pytest {posargs:-n auto}); files: 25 test, 19 source; deps: cloudpickle, hypothesis, pympler, pytest>9, pytest-xdist[psutil] from PyPI (note: attr.__version__ reads installed metadata; no entry points, so the harness writes none: such a test fails at the base (pre-existing)). Reference `PYTHONPATH=src python -m pytest tests`. |
| 3 | pytest-dev/pluggy (`49c0736`) | **selected**: runner: pytest (tox: pytest {posargs}; [pytest] testpaths = testing); files: 9 test, 13 source; deps: pytest>=8, pytest-benchmark from PyPI (coverage only for the coverage env); check 7: yes: pytest's plugin framework; its AGENTS.md/CLAUDE.md are contributor docs, never executed (note: pytest itself imports pluggy: with PYTHONPATH=src the code under test is also the runner's (as in its own tox)). Reference `PYTHONPATH=src python -m pytest testing`. |

*Python, standard library only at test time (quota 2):*

| # | Candidate | Decision |
|---|---|---|
| 4 | andialbrecht/sqlparse (`60cdc64`) | **selected**: runner: pytest (CI: pytest tests/); files: 10 test, 21 source; deps: standard library only at test time (pytest itself allowed); check 7: yes: an SQL parser; its AGENTS.md/CLAUDE.md are contributor docs, never executed. Reference `python -m pytest tests`. |
| 5 | python-hyper/h11 (`62c5068`) | **selected**: runner: pytest (tox: pytest --cov=h11 --cov-config=.coveragerc h11); files: 9 test, 11 source; deps: standard library only at test time (pytest; pytest-cov only for coverage) (note: test_against_stdlib_http serves on loopback, which a network-less container still has). Reference `python -m pytest h11`. |

*JavaScript, `node --test` (quota 2):*

| # | Candidate | Decision |
|---|---|---|
| 6 | affaan-m/ECC | excluded, check 7: an agent skill/plugin package (Skills, instincts, memory, ... for Claude Code, Codex, Opencode, Cursor) |
| 7 | coreyhaines31/marketingskills | excluded, check 7: an agent skill/plugin package (Marketing skills for Claude Code and AI agents) |
| 8 | fastify/fastify (`ce41dc0`) | excluded, check 3 (as held-out-4's wrapper-script rule): runner: no: `npm test` = lint && borp && tstyche; borp drives node:test through its own runner, not `node --test`. |
| 9 | koajs/koa (`a82feec`) | **selected**: runner: node --test (`npm test`); files: 73 files under __tests__, 7 in lib; deps: npm ci from the committed package-lock.json (supertest, ...). Reference `node --test`. |
| 10 | wekan/wekan (`a463937`) | excluded, check 3: runner: no: `npm test` = meteor test --driver-package meteortesting:mocha. |
| 11 | rmyndharis/OpenWA (`173916c`) | excluded, check 3: runner: no: `npm test` = jest. |
| 12 | openai/openai-node (`d342603`) | excluded, check 3: runner: no: `npm test` = ./scripts/test (a mock-server wrapper) running vitest. |
| 13 | open-gsd/gsd-core | excluded, check 7: a meta-prompting/spec framework that drives AI coding agents (Claude Code, Codex, ...) |
| 14 | jerrykuku/luci-theme-argon (`81e781c`) | excluded, check 3 (held-out-4 precedent: no root test script): runner: no: no root package.json, so no root `test` script. |
| 15 | mock-server/mockserver-monorepo (`f2106b2`) | excluded, check 3: runner: no: no root package.json (a Java monorepo). |
| 16 | qaiu/netdisk-fast-download (`e9be9b3`) | excluded, check 3: no root test script (a Java service; package.json has no scripts.test). |
| 17 | platformatic/platformatic (`68e94f4`) | excluded, check 3: test = pnpm -r --workspace-concurrency=1 --if-present test (a pnpm workspace script; held-out-4 precedent). |
| 18 | kai-scheduler/KAI-Scheduler (`96eb376`) | excluded, check 3: no root package.json (a Go project). |
| 19 | androoAGI/starnet (`d540d50`) | excluded, checks 7 and 3: a local-first desktop agent harness with a skills catalogue (check 7); test = npm run test:fast && npm run test:http, a chain of package scripts (check 3). |
| 20 | aurelia/aurelia (`10f3fd2`) | excluded, check 3: test = cd packages/__tests__ && npm run test (a workspace package's script). |
| 21 | umutxyp/MusicBot (`bf396aa`) | **selected**: test = node --test "test/*.test.js"; 14 test files, 52 source files; dependencies via npm ci from the lockfile; a Discord bot (not an agent package). Reference `node --test "test/*.test.js"`. |

*TypeScript through Node's type stripping (quota 1): **not met.***

| # | Candidate | Decision |
|---|---|---|
| 22 | block/buzz (`dc25198`) | excluded, check 3: no root test script (a Rust/pnpm monorepo). |
| 23 | langchain-ai/chat-langchain (`b8acf5c`) | excluded, check 3: no root package.json (the TypeScript is under frontend/; the root is a Python agent). |
| 24 | keslr/keslr_connect (`28a6ebf`) | excluded, check 3: test = vitest run. |
| 25 | cloudflare/forge (`91f52a4`) | excluded, check 3: test = pnpm -r run test (a pnpm workspace script). |
| 26 | openqodex/openqodex (`627c153`) | excluded, checks 7 and 3: a code-review tool that runs in coding agents, with plugins/ and skills/ (check 7); test = vitest run (check 3). |
| 27 | brijeshb42/monaco-themes (`92a2aa7`) | excluded, check 3: test = echo "Error: no test specified" && exit 1 (no tests). |
| 28 | Kronuz/Xapiand (`6961bb9`) | excluded, check 3: no root package.json (a C++ project). |
| 29 | Gan-Tu/Widgets (`cab3e76`) | excluded, check 3: test = npm run test:widgets = npm run build:widgets && node --experimental-strip-types --test tests/*.test.mjs: a build step, and the tests are .mjs, not .ts. |
| 30 | graphile-contrib/postgraphile-plugin-connection-filter (`3886658`) | excluded, check 3: test = jest -i. |
| 31 | Zero-wyc/ZViewer (`0af85d0`) | excluded, check 3: no root test script (a workspaces monorepo). |
| 32 | xrkseek/XRK-AGT (`63f004e`) | excluded, checks 7 and 3: an AI agent framework with agents/ and skill syncing (check 7); test = node tests/run.mjs unit, a custom runner script (check 3). |
| 33 | kiri-art/stable-diffusion-react-nextjs-mui-pwa (`0ea5986`) | excluded, check 3: test = vitest --run. |
| 34 | ProjectEvergreen/wcc (`11d7acb`) | excluded, check 3: test = mocha .. |
| 35 | snyk-snippets/modern-npm-package (`0372c17`) | excluded, check 4: test = node --experimental-strip-types --test passes check 3, but 1 test file and 1 source file. |
| 36 | WebMCP-org/npm-packages (`469bad2`) | excluded, checks 3 and 7: test = pnpm test:unit && pnpm test:e2e (a chain of workspace scripts, check 3); MCP tooling for agents (check 7). |
| 37 | Firstp1ck/pi-coding-agent-forge (`f5477c2`) | excluded, checks 7 and 3: extensions, skills and prompts for the Pi coding agent (check 7); no root test script (check 3). |
| 38 | leonardsellem/plaud-sync-for-obsidian (`9c7542e`) | excluded, check 3 (TypeScript rule): test = node --experimental-strip-types --test test/*.test.mjs: the tests are .mjs, not .ts. |
| 39 | OpenCoven/coven (`bb31bdf`) | excluded, checks 7 and 3: a runtime for AI coding-agent sessions with skills/ (check 7); no root package.json (check 3). |
| 40 | azu/eventmit (`ae5fc98`) | excluded, check 3: test = node --run build && node --run test:unit (a build step). |
| 41 | eliasm307/storybook-addon-deep-controls (`a9b3b7b`) | excluded, check 3: test = npm --prefix packages/addon run test && npm --prefix packages/example-v8 run test (workspace scripts). |
| 42 | ryanrasti/typegres (`b8fbf7d`) | excluded, check 3: test = vitest run. |
| 43 | fandsdev/eslint-config-fans (`a732014`) | excluded, check 3: test = pnpm run /^test:/ (a pnpm script chain). |

Every one of the 22 metadata-eligible TypeScript candidates fails check 3, 4 or 7. As
Amendment 4 requires, the quota is reported as not met and no candidate was
added. Unlike Amendment 3, Amendment 4 draws this quota from its own search
only. **TypeScript type stripping is therefore not re-validated by
held-out-5**; it was last measured on held-out-4 (skyhook, engine `ccb0622`).

**Final held-out-5 set (7 projects; pinned commits in `corpus.json`, set
`heldout5`):**
- Python with dependencies (pytest): marshmallow, attrs, pluggy.
- Python, standard library only (pytest): sqlparse, h11.
- JavaScript (`node --test`): koa, MusicBot.

**Notes recorded before measurement:**
- **pluggy:** pytest itself imports pluggy, so with `PYTHONPATH=src` the code
  under test is also the runner's.
- **attrs:** its `__version__` reads installed metadata, which the harness
  does not write (no entry points). A test of it fails at the base.
- **attrs and cattrs:** attrs was installed from PyPI into held-out-4's
  cattrs image as a dependency. Its tests, sources and configuration were
  never read, so check 8 does not apply.


## After the first held-out-5 results

**Harness and tooling changes, none to `src/`:**
- `cancelprobe.py`:
  - The script crashed after the first SIGTERM of each project, so nothing
    was recorded; the fix is one line (the `ps` rows unpacked into three
    values).
  - It now records whether the command was still running when signalled,
    and takes a `--delay` option used only for a run labelled post-hoc.
  - The crashed attempt is kept under `_superseded`.
- `harness.py`: accepts `--set heldout5` (before setup).

**Post-hoc runs** (labelled post-hoc in RESULTS.md; not validation): the
cancellation probe at a 0.2 s delay on pluggy, sqlparse, h11 and MusicBot.

## Held-out-6 freeze (PROTOCOL.md Amendment 5), recorded before any candidate is searched for

- **Frozen:** 2026-10-24T13:49Z, before the candidate search ran.
- **Engine under test:** main `083b6f1` (merge of #38), `src/` tree `0e1e1f4adcfa33ef493e8b6063f04a91d1c3a41f`. Installed from the wheel
  `repo_ai-0.7.7-py3-none-any.whl`, built from that commit with `SOURCE_DATE_EPOCH=1761264000`,
  sha256 `cf2c6b3c0d0d08ce6f2f70ab0a3ff5f0bf7c82afe1ec8de4beb0da75938e5061`, into a fresh virtualenv.
- **Measuring host:** macOS (Darwin 25.5.0, arm64, 14 cores), with node v24.19.0 on the host.
  podman 6.0.2 runs a 7-CPU, 2 GiB VM. Base images:
  - `docker.io/library/python:3.12-slim`: `sha256:18d23907c5d7ef2ca1b0ea8b4a73fe4a6ae47114c257a1afed8bc66c3886f8cb`
  - `docker.io/library/node:24-slim`: `sha256:156e9bc7a0a267cc6ca77b4283e32b123479342df684ce297455d7b95ff5a6b5`
- **Tooling, frozen in the commit that adds this section:**
  - `select_heldout6.py` holds the candidate lists and queries;
  - `scenarios.py` holds the labels, picks and validation;
  - `score6.py` holds the rules and gates;
  - `perf6.py` and `heldout6.py` hold the measurement order.
  - `harness.py` accepts `--set heldout6`.
- **Dry runs before the freeze, on previously used projects only:** cachetools, geojson-vt and h11, in
  `$VEV_WORK=v6dev`. They are development data, not results.
  - **Harness bugs they found, fixed before this freeze:**
    - evidence JSON was truncated before parsing;
    - a linked worktree needs its own `init`;
    - `node --test` handles the driver's SIGTERM, so a hang can end with a non-signal exit code;
    - in C1, the passing run was scored as the failing state's;
    - A2 is scored for G1 only.
  - **What they showed:** U5 (a staged rename) gave `nothing-selected` on all three projects. That is
    finding D9 in `docs/VERIFY-PHASE2-FINDINGS-2026-10.md`.
- **Known defects at freeze time:** D1–D9 (same document). No scenario was added or removed because
  of them.

## Held-out-6 selection (recorded before any held-out-6 project was set up, indexed or measured)

**Procedure:**
- `select_heldout6.py` ran once on 2026-10-24 after the freeze above. Its record is
  `results/heldout6/selection.json`.
- Check 8 excludes 3001 repositories named by earlier records or the corpus.
- **Code-search results:**

  | Query | Repositories | Eligible by metadata |
  |---|---|---|
  | JS `"describe, it" "node:test"` | 695 | 38 |
  | JS `"node:assert" "node:test"` | 883 | 30 |
  | TS `"describe, it" "node:test"` | 663 (135 metadata errors) | 31 |
  | TS `"node:assert" "node:test"` | 784 | 31 |
  | Jest `"testEnvironment" filename:jest.config.js` | 992 | 45 |
  | Vitest `"defineConfig" "test" filename:vitest.config.ts` | 524 | 40 |

- Candidates were then read one at a time, in list or star order: descriptions and `package.json`
  test scripts through the API, then a clone at the recorded head when check 3 passed.
- Every read and decision, in order (68 in all), is in `results/heldout6/reads.json`.
- **Check 1 is applied mechanically, as in held-out-3:** a repository GitHub reports as `NOASSERTION`
  is excluded. That excludes prettytable, networkx and sphinx.
- **One rule was decided during selection,** at candidate Homebrew/actions, before its test files
  were read: TypeScript test files are `.ts`, `.mts` or `.cts`, all of which node strips.

| Quota | Selected (pinned commit) | Reference command | Notes |
|---|---|---|---|
| Python, pytest, third-party deps (2) | **pyjwt** (`16231ab`) | `python -m pytest tests` | cryptography installed (the tox `crypto` env) |
| | **parsel** (`599897f`) | `python -m pytest docs parsel tests` | tox's default paths; pytest 9's native `[tool.pytest]` table; doctest modules |
| Python, unittest (2) | **mkdocs** (`2862536`) | `python -m unittest discover -s mkdocs -p "*tests.py"` | declares entry points (the harness writes their metadata) |
| | **websockets** (`60bc200`) | `PYTHONPATH=src python -m unittest` | its Makefile `tests` target; the C speedups are not built |
| Python, large suite (1) | **not met** | — | every eligible candidate had fewer than 60 test files: pygments 33, babel 42, werkzeug 27, alembic 39. networkx and sphinx failed check 1 |
| JavaScript, `node --test` (2) | **hubot** (`9aab11a`) | `node --test --test-timeout=40000` | node's default discovery also runs helper files under `test/` |
| | **jsonic** (`46b8655`) | `node --enable-source-maps --test test/**/*.test.js` | tests import the committed `dist/`. CI builds first, so a mutation of `src/*.ts` is invisible to the tests |
| TypeScript, type stripping (1) | **Homebrew/actions** (`d482da0`, `hb-actions`) | `node --test --experimental-test-module-mocks --import ./spec-helper.mts --test-reporter ./test-reporter.mts --test-reporter-destination stdout` | `.mts` tests; its own `--test-reporter`, so verify cannot add its per-test reporter |
| Unsupported runner, control (1) | **web-component-designer** (`557fbe2`, `wcd`) | `node --experimental-vm-modules node_modules/jest/bin/jest.js` | Jest. The command names `node_modules/` relative to the root, while the image installs at `/node_modules`; the replacement rule applies if the native suite fails at the base |

**Harness change, before any held-out-6 project was set up.** Node images put `/node_modules/.bin`
on `PATH`, as `npm` does when it runs a package script. This affects only images built from now on.

**After setup, before any `verify` run on them** (Amendments 5a and 5b in PROTOCOL.md):
- **hb-actions:** verify lists 0 test files (D10). Its harness universe is node 24's own default
  discovery: 20 files, of which 15 pass at the base and 5 fail (25%, so it is not replaced). The
  changes were regenerated with that universe: 20 mutations and 3 reverts, 12 of 23 detected.
- **wcd** (control): the native suite exits 1 at the base in its image, because its command names
  `node_modules/jest/bin/jest.js` relative to the root. It is **replaced** under the frozen rule.
  The next control candidates were read in order (`reads.json` 69–73):
  - yoroi: check 3;
  - remove-accents: check 4;
  - hypermod-community: check 5;
  - compdf: check 3;
  - **ha-map-card** (`0f2c9f9`): selected, with `jest`, 23 test files and `package-lock.json`.
- **Harness fix:** an opaque runner's suite is run with its own command (the empty `full` argv ran
  nothing).

## After the first held-out-6 results (post-hoc; none of it changes a frozen number)

- **`recheck6.py` and `score6.py --recheck`** (new). Every label a score uses is re-run three times,
  quietly and alone; a label confirmed fewer than 2 times is set aside. A change under a committed
  `node_modules/` counts as a harness artifact. The frozen scorer's default path is unchanged.
- **`scenarios.files_truth`:** a unique work directory per call. The recheck's second run of the same
  file failed on a stale podman bind mount of a reused path.
- **perf6 sample:** perf6 ran stand-alone, so its sample is wallclock's default of 8+8 changes per
  project, not the 6+6 that `heldout6.py` sets. Recorded, not repeated.
- **hubot host measurement stopped.** The native suite under the host sandbox did not finish in
  41 min at 0% CPU, so there are no hubot host data.
- **hb-actions host:** not measured, because `npm ci` would rewrite its committed `node_modules/`.
- **The wallclock tool's native time for an opaque runner is invalid** (its empty `full` argv). The
  ha-map-card native time is taken from the 5a run (2.08 s).
- **Host load:** the load average varied between 3 and 20 during performance runs (shared machine),
  and is recorded per project in `results/heldout6/log-perf.log`.
