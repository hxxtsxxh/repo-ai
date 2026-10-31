---
name: b-skill-25
description: Harden filesystem permissions for config and secret files.
license: Apache-2.0
---

# File Permission Hardening

Set least-privilege permissions on sensitive files.

## Guidance

- Secret and key files should be owner-read/write only: `chmod 600 ~/.ssh/id_ed25519`.
- SSH directory itself: `chmod 700 ~/.ssh`.
- Config with secrets: `chmod 600`; shared read-only config: `644`.
- Avoid `chmod 777`; it grants everyone write access and is almost never correct.
- Verify ownership with `ls -l` and fix with `chown` where appropriate.

Tight permissions limit the blast radius if an account is compromised.
