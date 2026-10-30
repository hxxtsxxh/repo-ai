#!/bin/sh
# Clean-environment smoke of an installed repo-ai: fresh venv, offline first run, a sandboxed
# verify (when a sandbox backend works here), and uninstall that keeps the user's own edits.
#
#   sh scripts/release_smoke.sh ./dist/repo_ai-0.9.0-py3-none-any.whl     # a built wheel
#   sh scripts/release_smoke.sh 'repo-ai==0.9.0'                          # from PyPI (after publication)
#
# Needs python3 (3.10+) and git. Makes no model call and starts no provider. Writes only under a
# new temporary directory, which it prints. Exit status: 0 when every check holds.
set -u
SPEC=${1:?usage: release_smoke.sh WHEEL_OR_REQUIREMENT [EXPECTED_VERSION]}
WANT=${2:-}
PY=${PYTHON:-python3}
WORK=$(mktemp -d "${TMPDIR:-/tmp}/repo-ai-smoke.XXXXXX")
echo "work dir: $WORK"
fail=0
check() { if "$@"; then echo "ok   $*"; else echo "FAIL $*"; fail=1; fi; }
step() { echo; echo "\$ $*"; "$@"; rc=$?; echo "[exit $rc]"; return $rc; }

"$PY" -m venv "$WORK/v" || exit 1
if [ -x "$WORK/v/bin/python" ]; then BIN="$WORK/v/bin"; else BIN="$WORK/v/Scripts"; fi
"$BIN/python" -m pip install -q --disable-pip-version-check "$SPEC" pytest || { echo "FAIL install $SPEC"; exit 1; }
PATH="$BIN:$PATH"; export PATH
unset AI_AGENT VIRTUAL_ENV

step repo-ai --version
version=$(repo-ai --version | awk '{print $2}')
[ -n "$WANT" ] && check [ "$version" = "$WANT" ]
check "$BIN/python" -c "import repo_ai, sys; sys.exit(0 if 'site-packages' in repo_ai.__file__ else 1)"
check "$BIN/python" -m pip check

P="$WORK/proj"; mkdir -p "$P" && cd "$P" || exit 1
printf 'def mean(xs):\n    return sum(xs) / len(xs)\n' > calc.py
printf 'from calc import mean\n\n\ndef test_mean():\n    assert mean([1, 2, 3]) == 2\n' > test_calc.py
printf '# Notes\n\nHand-written line that must survive uninstall.\n' > CLAUDE.md
git init -q && git add -A && git -c user.email=smoke@example.invalid -c user.name=smoke commit -qm init

check step repo-ai quickstart
check step repo-ai agents list
check step repo-ai "do" "make mean return 0 for an empty list" --dry-run
check step repo-ai init --agent claude -q
printf 'def mean(xs):\n    return sum(xs) / len(xs) if xs else 0\n' > calc.py
check step repo-ai verify
if repo-ai sandbox status | grep -q "untrusted code will run in"; then
  check step repo-ai verify --run
  check step repo-ai evidence
else
  echo "(no working sandbox backend here: verify --run must refuse and run nothing)"
  repo-ai verify --run >/dev/null 2>&1; rc=$?
  check [ "$rc" -ne 0 ]
fi
check step repo-ai privacy audit
git checkout -q calc.py
check step repo-ai uninstall --agent all --yes
check grep -q "Hand-written line that must survive uninstall." CLAUDE.md
check [ -z "$(git status --porcelain)" ]

echo
[ "$fail" -eq 0 ] && echo "SMOKE PASS ($version)" || echo "SMOKE FAIL ($version)"
exit "$fail"
