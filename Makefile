.DEFAULT_GOAL := help
SHELL := /bin/bash
DATE = $(shell date +%Y-%m-%d:%H:%M:%S)

APP_VERSION_FILE = app/version.py

GIT_BRANCH ?= $(shell git symbolic-ref --short HEAD 2> /dev/null || echo "detached")
GIT_COMMIT ?= $(shell git rev-parse HEAD)

.PHONY: help generate-version-file test freeze-requirements test-requirements coverage clean format smoke-test run run-celery run-celery-clean run-celery-beat run-celery-perge

help:
	@cat $(MAKEFILE_LIST) | grep -E '^[a-zA-Z_-]+:.*?## .*$$' | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

generate-version-file: ## Generates the app version file
	@printf "__commit_sha__ = \"${GIT_COMMIT}\"\n__time__ = \"${DATE}\"\n" > ${APP_VERSION_FILE}

test: generate-version-file ## Run tests
	./scripts/run_tests.sh

freeze-requirements:
	poetry lock --no-update

test-requirements:
	poetry lock --check

coverage: venv ## Create coverage report
	. venv/bin/activate && coveralls

clean:
	rm -rf node_modules cache target venv .coverage build tests/.cache

format:
	poetry run isort .
	poetry run black --config pyproject.toml .
	poetry run flake8 .
	poetry run mypy .

smoke-test:
	cd tests_smoke && poetry run python smoke_test.py

run: ## Run the web app
	flask run -p 6011 --host=0.0.0.0

run-celery: ## Run the celery workers
	./scripts/run_celery.sh

run-celery-clean: ## Run the celery workers but filter out common scheduled tasks
	./scripts/run_celery.sh 2>&1 >/dev/null | grep -Ev 'beat|in-flight-to-inbox|run-scheduled-jobs|check-job-status'

run-celery-beat: ## Run the celery beat
	./scripts/run_celery_beat.sh

run-celery-perge: ## Purge the celery queues
	./scripts/run_celery_purge.sh
