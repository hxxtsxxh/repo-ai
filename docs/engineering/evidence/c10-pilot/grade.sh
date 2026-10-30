#!/bin/sh
# usage: grade.sh <project dir> <task t1|t2|t3>; prints "<passed>/<total>"
d=$1; t=$2; o=$(cd "$(dirname "$0")/oracle" && pwd)
out=$(cd "$d" && PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider --tb=no -rA --rootdir=. -o pythonpath=. "$o/test_$t.py" 2>&1)
p=$(printf '%s\n' "$out" | grep -c '^PASSED')
n=$(grep -c '^def test_' "$o/test_$t.py")
echo "$p/$n"
