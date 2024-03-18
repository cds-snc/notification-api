#!/bin/bash
#
# Run project tests
#
# NOTE: This script expects to be run from the project root with
# ./scripts/run_tests.sh

set -o pipefail

function display_result {
  RESULT=$1
  EXIT_STATUS=$2
  TEST=$3

  if [ $RESULT -ne 0 ]; then
    echo -e "\033[31m$TEST failed\033[0m"
    exit $EXIT_STATUS
  else
    echo -e "\033[32m$TEST passed\033[0m"
  fi
}

ruff format --check
display_result $? 1 "Code style check"

# Run tests in concurrent threads when able and serial otherwise
# https://docs.pytest.org/en/stable/reference/customize.html
params="-rfe --disable-pytest-warnings --cov=app --cov-report=term-missing --junitxml=test_results.xml -q"
pytest ${params} -n auto -m "not serial" tests/ && pytest ${params} -m "serial" tests/
display_result $? 2 "Unit tests"
