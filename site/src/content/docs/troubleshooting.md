---
title: Troubleshooting
description: Fixes for the common problems with context injection, stale indexes, verify's test command, sandboxes and missions.
---

Start with the two diagnostic commands:

```sh
repo-ai quickstart     # where you are and what to run next
repo-ai doctor         # installation and agent wiring (add --agent claude for Claude Code)
```

## Context and the index

| Symptom | Fix |
|---|---|
| No context appears in Claude Code | Restart the session (hooks load at start), then run `repo-ai doctor --agent claude` |
| Context still does not appear | Run `which repo-ai` from the shell Claude uses: hooks call `repo-ai` by name and do nothing if it is missing |
| Context appears but looks stale | `repo-ai status` (exits 2 when stale), then `repo-ai update` |
| Results look off | `repo-ai explain "<task>"` shows the score breakdown for each file |
| Hook diagnostics needed | Set `REPO_AI_HOOK_DEBUG=1` before starting `claude` |
| `settings.json is not valid JSON` | repo-ai will not overwrite it. Fix the JSON, then `repo-ai update` |
| An index from a newer repo-ai | Upgrade repo-ai, or `repo-ai rebuild` |
| `doctor` warns about two versions | The `repo-ai` on `PATH` differs from the one running. Hooks use the one on `PATH` |

## Verify

| Symptom | Fix |
|---|---|
| "cannot establish the test command"; nothing runs | Pass it once: `repo-ai verify --test-command "PYTHONPATH=src python -m pytest tests"`, or set `verify_test_command` in `.repo-ai/config.toml` |
| No sandbox available | `repo-ai sandbox status`. On Linux install `bubblewrap`; on Windows install podman or Docker and pass `--sandbox podman` or `--sandbox docker` |
| bubblewrap fails to start on Ubuntu | Unprivileged user namespaces are restricted; see the note on the [CI recipe](/repo-ai/docs/ci/#notes), or use a container sandbox |
| Tests fail in the sandbox but pass locally because of missing dependencies | Use the project's own environment (a host sandbox uses the project's interpreter), or build a local image and pass `--sandbox podman --image REF` |
| `not verified: no test is linked to the behavioural change` | No test reaches the change. Write one, run `repo-ai verify --record` once for runtime links, or run `--full` |
| Confidence is `MEDIUM` or `LOW` | The output lists the reasons. `repo-ai verify --record` adds runtime evidence; a changed test, build or dependency file requires the full suite |
| `repo-ai evidence` says the evidence is stale | The working tree or test environment changed since the last run. Run `repo-ai verify --run` again |
| A run is slower than running the suite yourself | Expected on short suites: planning, the copy and the integrity check cost about 0.6–1 s |
| A container is left running after you killed `repo-ai` | Possible on Windows; remove it with `podman ps` / `docker ps` and `rm -f` |

## Missions

| Symptom | Fix |
|---|---|
| `BLOCKED: Checkout has changes` | Missions need a clean, committed tree. Commit or stash, then run again |
| `ASK_APPROVAL: …` | This is the default plan-only result. Live execution needs `--run --allow-live-provider` and explicit `--allow-write` paths |
| `--agent auto` returns `NOT_AUTHORIZED` or `NO_AGENT` | `repo-ai agents route` explains why; `repo-ai agents authorize NAME` authorises a provider |
| A USD ceiling is refused | The provider cannot enforce one (Codex, agy). Use `--max-seconds` instead; cost is recorded as `UNKNOWN` |
| Claude as `--agent claude` fails to authenticate | Expected: its login does not work in repo-ai's isolated scratch HOME. See [Providers](/repo-ai/docs/providers/) |
| `apply` refuses | You edited a target file, a path is a symlink, or the change adds, deletes or renames files. Review and apply that manually |
| `why-test-failed` exits 2 with `INCONCLUSIVE` | The recorded evidence is incomplete or stale; it never reruns tests to fill the gap |
| Missions on Windows | Not supported. Use macOS or Linux |
