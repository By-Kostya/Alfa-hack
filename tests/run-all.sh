#!/bin/sh
set -eu
root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
cd "$root"
stamp=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p tests/reports
report="tests/reports/$stamp.md"
: > "$report"
status=0
for suite in backend/tests/run.sh; do
  set +e
  sh "$suite"
  code=$?
  set -e
  echo "$suite exit=$code" >> "$report"
  if [ "$code" -ne 0 ]; then
    status=$code
  fi
done
exit "$status"
