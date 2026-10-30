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
