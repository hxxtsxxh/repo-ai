#!/usr/bin/env bash
# Format a single edited file with the project's local formatters, if available.
set -euo pipefail
f="${1:-}"
[ -z "$f" ] && exit 0
case "$f" in
  *.py)  command -v black >/dev/null && black -q "$f" || true ;;
  *.ts|*.tsx|*.js|*.jsx|*.json|*.css|*.md)
         command -v prettier >/dev/null && prettier --write "$f" >/dev/null || true ;;
esac
exit 0
