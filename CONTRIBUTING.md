# Contributing to repo-ai

Thanks for helping. repo-ai's value is that its output can be trusted, so the bar
for a change is evidence, not volume.

## Ground rules

- **Say exactly what was observed.** A verdict, doc line or log message must not
  claim more than the code checked. "Tests passed" is never "the task is correct".
- **Bug fixes start with a failing test.** Add the regression test first, show it
  fails on the old code, then fix.
- **No hidden network or model calls.** `--dry-run`, `agents list|doctor|route`,
  `quickstart`, `status`, `help` and every offline command must stay
  non-billable and offline.
- **Security-sensitive areas** (`src/repo_ai/verify/`, `sandbox*`, `mission/`,
  `security.py`, `fsutil.py`, `paths.py`, hooks): include an adversarial test
  (symlink, traversal, hostile repository text) for the case you change.
- **Experimental means labelled.** New features ship as experimental in
  [docs/STATUS.md](docs/STATUS.md) until a preregistered or held-out evaluation
  supports a stronger label.

## Development setup

```sh
git clone https://github.com/hxxtsxxh/repo-ai.git && cd repo-ai
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
python -m pip install -e ".[dev]" ruff mypy build
```

## Checks to run before a pull request

```sh
ruff check src tests benchmarks/run.py scripts
mypy
python scripts/build_plugin.py --check     # the Claude Code plugin bundle is current
python scripts/gen_cli_reference.py --check  # the CLI reference matches --help
python -m pytest -q                        # about 20 minutes for the full suite
```

The full suite runs isolation tests that need a sandbox backend: seatbelt on
macOS, bubblewrap on Linux, or podman/docker. Tests that need an unavailable
backend skip with a reason; CI runs each backend.

Release qualification (maintainers) uses three disjoint shards from a clean
clone: `python scripts/finalization_validate.py --help`.

### Security-fixture tests

Some tests write attack-like fixtures to disk for the skill and plugin vetting checks to read (reverse and bind
shells, recursive deletes, credential or environment uploads, `curl … | sh`), or make real escape attempts that
the sandbox must deny (network connections, reads of credential paths). **Nothing in the suite executes a
fixture**, but endpoint protection on a managed machine cannot tell a fixture from a payload.

- These modules are listed in `tests/conftest.py` (`SECURITY_FIXTURE_MODULES`) and **skipped locally by
  default**. CI sets `REPO_AI_SECURITY_FIXTURES=1` for every job: every pull request runs them on Linux and
  Windows, and on macOS (seatbelt) in the `test-macos-security` job. `tests/test_security_fixture_policy.py`
  fails if the workflow stops doing so. A CI run skipped with `[skip ci]` runs none of them.
- Release qualification treats a skip as a failure, so it needs the variable set, on a machine where that is
  allowed.
- To run them yourself, use a machine or VM where that is allowed: `REPO_AI_SECURITY_FIXTURES=1 python -m pytest`.
- The vetting benchmark (`benchmarks/skill-vet-fresh-v1/`) reads an 80-case defanged corpus and refuses to run
  without the same variable. Its corpus is plain data: no file is executable, every host is under `.invalid` or
  `example.com`.
- Put new attack-like fixtures in a listed module (or add the module), write them as data the test only reads,
  and never as a command line (`python -c "<payload>"`). Never weaken a check to avoid a detection, and never
  disguise a fixture to get past one.

## Pull requests

- One coherent change per PR, with the commands you ran and their results.
- Update `CHANGELOG.md` under the unreleased heading, and `docs/STATUS.md` if a
  capability's status or evidence changes.
- Don't commit generated state (`.repo-ai/`), credentials, provider
  transcripts or third-party code without its licence.

## Reporting security issues

Please do **not** open a public issue. See [SECURITY.md](SECURITY.md).

## Code of conduct

Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).
