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
"$py" -m unittest discover -s tests -p 'test_*.py'
code=$?
set -e
{
  echo "command: $py -m unittest discover -s tests -p 'test_*.py'"
  echo "exit: $code"
} > "tests/reports/$stamp.md"
exit "$code"
