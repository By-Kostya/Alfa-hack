#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
stamp=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p tests/reports
py=python3
if command -v python >/dev/null 2>&1; then
  py=python
fi
set +e
"$py" -m unittest tests.test_pipeline
code=$?
set -e
{
  echo "command: $py -m unittest tests.test_pipeline"
  echo "exit: $code"
} > "tests/reports/$stamp.md"
exit "$code"
