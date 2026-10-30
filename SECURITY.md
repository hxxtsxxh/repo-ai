# Security policy

## Supported versions

| Version | Supported |
|---|---|
| latest `0.9.x` release | yes |
| `0.9.0.devN` pre-releases, `0.8.0rc1`, `0.7.x` and older | no — upgrade |

## Reporting a vulnerability

Please report vulnerabilities **privately** via GitHub's
[private vulnerability reporting](https://github.com/hxxtsxxh/repo-ai/security/advisories/new)
("Report a vulnerability" on the Security tab). Do not open a public issue.

Include the repo-ai version (`repo-ai --version`), OS, sandbox backend
(`repo-ai sandbox status`), and a minimal reproduction. Expect an initial
response within 7 days. Fixes are released as a patch version with a
changelog entry and credit if you want it.

In scope, for example: escaping the verify/mission sandbox; writing or
deleting outside the repository or through a symlink; a repository's own files
causing repo-ai to execute a program, call a model or send data without the
user's consent; secrets or prompt text persisted or transmitted; integrity
checks (evidence, handoff capsules, apply/undo receipts) that can be forged to
make repo-ai report or apply something it did not verify.

## Threat model and known limitations

The design, invariants and per-OS limits are documented in
[docs/SECURITY.md](docs/SECURITY.md) and
[docs/VERIFY-THREAT-MODEL.md](docs/VERIFY-THREAT-MODEL.md). Notably: Windows has
no host sandbox (use a podman/docker backend), and the live-provider sandbox
restricts writes but does not isolate host reads.
