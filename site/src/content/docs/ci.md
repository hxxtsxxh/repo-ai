---
title: CI recipe
description: An example GitHub Actions job that runs repo-ai verify --run on a pull request, with bubblewrap as the sandbox.
---

:::caution[Example — not run by the maintainers]
This workflow has not been run by the repo-ai maintainers. It is assembled from documented behaviour and from the
bubblewrap setup repo-ai's own CI uses for its sandbox tests. Adapt it to your project and test it before you rely
on it.
:::

`verify --run` exits **0** only for a passing verdict (`selected-and-full-suite-passed`,
`selected-passed (full suite not run)`, or `nothing-selected` for a change with no behavioural effect). Every other
verdict, including `regression`, `failing (…)` and any `not verified: …`, exits **1**, and a cancelled run exits
**130**. That makes it usable as a CI step as-is.

## Before you add it

1. Run `repo-ai init --agent none` locally and **commit** `.repo-ai/config.toml`, `.repo-ai/context/` and the
   `.gitignore` block, so the CI checkout starts from the same configuration. The index itself
   (`.repo-ai/state/`) is never committed and is rebuilt in CI.
2. If `repo-ai verify` cannot establish your test command, set `verify_test_command` in `.repo-ai/config.toml`.
3. Make the release wheel reachable from CI (see [Install](/repo-ai/docs/install/)) and put its URL or path in the
   `REPO_AI_WHEEL` variable below.

## Workflow

```yaml
# .github/workflows/verify.yml  — EXAMPLE, untested by the repo-ai maintainers
name: repo-ai verify
on:
  pull_request:

permissions:
  contents: read

jobs:
  verify:
    runs-on: ubuntu-latest
    env:
      REPO_AI_WHEEL: ${{ vars.REPO_AI_WHEEL }}   # the wheel URL or path from the Install page
    steps:
      - uses: actions/checkout@v7
        with:
          fetch-depth: 0               # verify needs the base revision's history

      - uses: actions/setup-python@v7
        with:
          python-version: "3.12"

      - name: Install the project's test dependencies
        run: python -m pip install -r requirements.txt pytest   # adapt to your project

      - name: Install repo-ai
        run: python -m pip install "$REPO_AI_WHEEL"

      - name: Install bubblewrap and allow unprivileged user namespaces
        run: |
          sudo apt-get update -q && sudo apt-get install -y -q bubblewrap
          sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0 || true

      - name: Index the repository
        run: |
          repo-ai init --agent none
          git status --porcelain       # should be empty if the init output is committed
          repo-ai sandbox status

      - name: Verify the pull request against its base
        run: repo-ai verify --run --base "origin/${{ github.base_ref }}"
```

## Notes

- **User namespaces.** bubblewrap needs unprivileged user namespaces. Recent Ubuntu images restrict them through
  AppArmor; the `sysctl` line relaxes that on the runner, as repo-ai's own sandbox CI job does. On a runner where you
  cannot change it, use a container instead: install Docker or podman and pass `--sandbox docker` (with `--image` for
  an image that has your dependencies; it must exist locally and is never pulled).
- **Full suite before merge.** The selection is not the full suite. Add `--full` to run the whole suite in the same
  sandbox, or keep your existing test job alongside this one.
- **Time bound.** `--deadline SECONDS` caps the total wall-clock of all test processes; anything it cuts makes the run
  "not verified", never a pass.
- **Machine-readable output.** Add `--json` for a `summary` object (`verdict`, `new_failures`, `pre_existing`, …)
  you can post as a comment with your own tooling. repo-ai itself does not post anything.
- **Windows runners** have no host sandbox; use `--sandbox docker` or `--sandbox podman`.
- **What a green check means:** the tests that ran observed a pass in the sandbox. It is not a statement that the
  change is correct.
