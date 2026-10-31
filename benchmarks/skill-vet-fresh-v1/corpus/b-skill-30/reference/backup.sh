#!/usr/bin/env bash
# Sample local backup using rsync to a user-provided destination.
# Review and adjust DEST before using. This is reference material, not auto-run.
set -euo pipefail
SRC="${1:-$PWD}"
DEST="${2:?usage: backup.sh [src] <dest-dir>}"
rsync -a --delete \
  --exclude node_modules --exclude .venv --exclude build \
  "$SRC"/ "$DEST"/
echo "backup written to $DEST"
