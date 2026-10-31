---
name: b-skill-30
description: Set up reliable, verifiable local backups of a project directory.
license: MIT
---

# Local Backup Helper

Make dependable local backups you can actually restore.

## Approach

- Back up to a local or user-controlled location (an external drive, a self-hosted store).
- Exclude regenerable paths (`node_modules/`, `.venv/`, `build/`) to keep backups small.
- Keep secret files out of shared backups, or encrypt the archive at rest.
- Periodically test a restore; an untested backup is a hope, not a backup.
- Old backups can be pruned with care; see `reference/backup.sh` for a sample `rsync` command.

Document where backups live and how to restore them.
