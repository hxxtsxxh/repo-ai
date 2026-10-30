# Freeze qualification: `9663ac3` (repo-ai-cli 0.9.0)

Commit `9663ac3ad0145c1100f7a1a3204d7225e408c5d8`, tree `d83320bb89155c3b89ff76cf0cbd6c63f92eed17`. Later commits on the
branch change only `docs/`, `site/` content and launch tooling (`git diff 9663ac3 HEAD -- src tests` is empty). Raw
evidence: ignored `dist/launch/qual-9663ac3/`.

| Check | Result |
|---|---|
| Full suite, 3 disjoint shards from a fresh detached clone (`scripts/finalization_validate.py`), macOS, Python 3.12.14 | **PASS**: 2274 collected, 2266 passed, 8 xfailed, 0 failed; exactly once; source unchanged; exits [0, 0, 0] |
| ruff (`src tests benchmarks/run.py scripts benchmarks/abc-v3 abc-v4 abc-v5`), mypy (117 files), `build_plugin --check`, `gen_cli_reference --check`, compileall, `git diff --check origin/main..HEAD`, actionlint (all workflows), added-line secret grep | all pass |
| Wheel `repo_ai_cli-0.9.0-py3-none-any.whl` | sha256 `b351d80e737764d749c52ed0f9af8d96c5e3ec313ed25f68ca743ab2238db17f` |
| sdist `repo_ai_cli-0.9.0.tar.gz` | sha256 `0f1802e407003f67bc9e75868f00b5e060d8999e94dd3fa0b54dbb3fad306b96` |
| Wheel rebuilt from the unpacked sdist | **byte-identical** (same sha256) |
| `twine check --strict` | PASSED (wheel and sdist); metadata `Name: repo-ai-cli`, `Version: 0.9.0` |
| Artifact contents | no benchmarks outside `benchmarks/tasks`, no sealed-v2/authoring/verify-eval, no `docs/research`, `docs/launch` or `site/` (sdist 2256, wheel 1936 entries) |
| `scripts/release_smoke.sh` on the wheel | macOS (seatbelt) PASS 14 checks; clean `python:3.12-slim` (no sandbox; `verify --run` refuses) PASS 13; privileged container with bubblewrap PASS 14 |
| Upgrade from the published `v0.9.0-dev4` wheel (clean container) | uninstall `repo-ai`, install `repo-ai-cli`: existing index read, `doctor` ok, `update`, uninstall restores the tree and keeps user `CLAUDE.md` lines |
| Linux bwrap isolation suites (privileged podman) | 109 passed, 4 skipped |
| Live journeys on this build | see `LIVE-JOURNEYS-2026-10-29.md` (Codex single; Codex+agy comparison; Codex→agy handoff with hidden oracle 714/714) |
| Independent adversarial review of the cycle's `src/` changes | no path to a false PASS / "no new failures" / "pre-existing"; 2 medium + 5 low findings, all fixed with failing-first tests before this freeze |

**Not run at this freeze:** Windows (CI is billable while the repository is private; it runs on the public repository's
CI), GitHub Actions of any kind, Bob/Gemini live, the abc-v5 confirmatory phase.
