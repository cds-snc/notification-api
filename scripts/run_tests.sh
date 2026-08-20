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

  if [ "$RESULT" -ne 0 ]; then
    echo -e "\033[31m$TEST failed\033[0m"
    exit "$EXIT_STATUS"
  else
    echo -e "\033[32m$TEST passed\033[0m"
  fi
}

make generate-openapi
OPENAPI_FILES=("openapi/v2-notifications-api-en.yaml" "openapi/v2-notifications-api-fr.yaml")
if ! git diff --exit-code -- "${OPENAPI_FILES[@]}" > /dev/null 2>&1; then
  echo -e "\033[31mOpenAPI files are out of date. Run 'make generate-openapi' and commit the changes.\033[0m"
  git diff -- "${OPENAPI_FILES[@]}"
  exit 1
fi
display_result 0 1 "OpenAPI files up to date check"

make test-requirements
display_result $? 1 "Requirements check"

ruff check .
display_result $? 1 "Code style check"

ruff check --select I .
display_result $? 1 "Import order check"

ruff format --check .
display_result $? 1 "Code format check"

mypy .
display_result $? 1 "Type check"

# Run tests that need serial execution.
if ! docker info > /dev/null 2>&1; then
  echo "This test uses docker, and it isn't running - please start docker and try again."
  exit 1
fi
pytest --disable-pytest-warnings --cov=app --cov-report=term-missing tests/ --junitxml=test_results_serial.xml -v --maxfail=10 -m "serial"
display_result $? 2 "Unit tests [serial]"

# Run with auto-detected concurrent workers.
pytest --disable-pytest-warnings --cov=app --cov-report=term-missing tests/ --junitxml=test_results.xml -n auto -v --maxfail=10 -m "not serial"
display_result $? 2 "Unit tests [concurrent]"
