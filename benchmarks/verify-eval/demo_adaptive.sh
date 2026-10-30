#!/bin/sh
# Usage: DEMO_SCRATCH=/path REPO_AI_BIN=/path/to/venv/bin sh demo_adaptive.sh
# The adaptive workflow on a fresh clone of cachetools (public, MIT), recorded verbatim.
S=${DEMO_SCRATCH:?set DEMO_SCRATCH to a scratch directory holding vev/repos/cachetools}
D=$S/demo2-cachetools
rm -rf $D && git clone -q --local --no-hardlinks $S/vev/repos/cachetools $D && cd $D || exit 1
git checkout -q --detach "$(git -C $S/vev/repos/cachetools rev-parse HEAD)"
export HOME=$S/vev/home REPO_AI_NO_BACKGROUND=1 PATH=$REPO_AI_BIN:/usr/bin:/bin
digest() { (git ls-files -z --cached --others --exclude-standard; printf '.git/HEAD\0.git/index\0') | xargs -0 shasum -a 256 2>/dev/null | shasum -a 256 | cut -c1-16; }
say() { printf '\n$ %s\n' "$*"; t0=$(python3 -c 'import time;print(time.time())'); "$@"; rc=$?; t1=$(python3 -c 'import time;print(time.time())'); python3 -c "print('[exit $rc, %.1fs]' % ($t1-$t0))"; }
echo "# 0. index once (no agent needed); record which code each test executes (once; also times the full suite)"
say repo-ai init --agent none -q
git add -A && git -c user.email=d@d -c user.name=d commit -qm "repo-ai init"
say repo-ai verify --record
echo "# 1. a developer edits a function (uncommitted)"
python3 - <<'PY'
p = "src/cachetools/__init__.py"
t = open(p).read()
old = "        if maxsize < 0:"
assert old in t, "edit site"
open(p, "w").write(t.replace(old, "        if maxsize < -1:", 1))
PY
git diff --stat
echo "source tree digest before: $(digest)"
echo "# 2-4. what changed, which tests matter and why, how sure (read-only)"
say repo-ai verify
echo "# 5-6. run it: sandboxed, in a disposable copy; new failures vs pre-existing"
say repo-ai verify --run
echo "source tree digest after:  $(digest)"
echo "# again, nothing changed: the evidence for this exact state is reused"
say repo-ai verify --run
echo "# 7. does the evidence still cover the working tree? (the developer reverts the bug)"
say repo-ai evidence
git checkout -q -- src/cachetools/__init__.py
say repo-ai evidence
echo "# a passing change: same workflow"
python3 - <<'PY'
p = "src/cachetools/__init__.py"
t = open(p).read()
open(p, "w").write(t.replace("        if maxsize < 0:", "        if not maxsize >= 0:", 1))
PY
say repo-ai verify --run
echo "# machine-readable summary for agents"
repo-ai verify --run --json | python3 -c "import json,sys; print(json.dumps(json.load(sys.stdin)['summary'], indent=1))"
git checkout -q -- src/cachetools/__init__.py
