#!/bin/sh
# Claude Code hook dispatcher for repo-ai (plugin copy).
# Inert in repositories without a repo-ai index.
#
# Contract: never block the user. Whatever happens inside repo-ai, this script
# exits 0 (exit code 2 would block a prompt), prints nothing on failure, and
# silently does nothing when repo-ai is not installed.
command -v repo-ai >/dev/null 2>&1 || exit 0
REPO_AI_IN_HOOK=1
export REPO_AI_IN_HOOK
if [ -n "${REPO_AI_HOOK_DEBUG:-}" ]; then
  repo-ai hook claude "$1"
else
  repo-ai hook claude "$1" 2>/dev/null
fi
exit 0
