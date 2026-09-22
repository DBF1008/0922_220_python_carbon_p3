#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="${PYTHON:-${PYTHON_BIN:-python3}}"
TEST_DIR="$ROOT_DIR/lib/carbon/tests"

export GRAPHITE_NO_PREFIX=true
export PYTHONPATH="$ROOT_DIR/lib${PYTHONPATH:+:$PYTHONPATH}"

if (($# > 0)); then
  exec "$PYTHON_BIN" -m twisted.trial "$@"
fi

failed=()
total=0
passed=0

for test_path in "$TEST_DIR"/test_*.py; do
  test_name="carbon.tests.$(basename "$test_path" .py)"
  total=$((total + 1))

  echo "==> Running $test_name"
  if "$PYTHON_BIN" -m twisted.trial "$test_name"; then
    passed=$((passed + 1))
  else
    failed+=("$test_name")
  fi
done

echo
echo "Unit scripts: $passed/$total passed"

if ((${#failed[@]} > 0)); then
  echo "Failed: ${failed[*]}"
  exit 1
fi
