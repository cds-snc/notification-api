.DEFAULT_GOAL := help
SHELL := /bin/bash
DATE = $(shell date +%Y-%m-%d:%H:%M:%S)

APP_VERSION_FILE = app/version.py

GIT_BRANCH ?= $(shell git symbolic-ref --short HEAD 2> /dev/null || echo "detached")
GIT_COMMIT ?= $(shell git rev-parse HEAD)

.PHONY: help
help:
	@cat $(MAKEFILE_LIST) | grep -E '^[a-zA-Z_-]+:.*?## .*$$' | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

.PHONY: generate-version-file
generate-version-file: ## Generates the app version file
	@printf "__commit_sha__ = \"${GIT_COMMIT}\"\n__time__ = \"${DATE}\"\n" > ${APP_VERSION_FILE}

.PHONY: test
test: generate-version-file ## Run tests
	./scripts/run_tests.sh

.PHONY: freeze-requirements
freeze-requirements:
	poetry lock --no-update

.PHONY: test-requirements
test-requirements:
	poetry lock --check

.PHONY: coverage
coverage: venv ## Create coverage report
	. venv/bin/activate && coveralls

.PHONY: clean
clean:
	rm -rf node_modules cache target venv .coverage build tests/.cache

.PHONY: format
format:
	poetry run isort .
	poetry run black --config pyproject.toml .
	poetry run flake8 .
	poetry run mypy .

.PHONY: smoke-test
smoke-test:
	cd tests_smoke && poetry run python smoke_test.py

.PHONY: smoke-test-local
smoke-test-local:
	cd tests_smoke && poetry run python smoke_test.py --local --nofiles

.PHONY: run
run: ## Run the web app
	flask run -p 6011 --host=0.0.0.0

.PHONY: run-celery
run-celery: ## Run the celery workers
	./scripts/run_celery.sh

.PHONY: run-celery-clean
run-celery-clean: ## Run the celery workers but filter out common scheduled tasks
	./scripts/run_celery.sh 2>&1 >/dev/null | grep -Ev 'beat|in-flight-to-inbox|run-scheduled-jobs|check-job-status'

.PHONY: run-celery-sms
run-celery-sms: ## run the celery workers for sms from dedicated numbers
	./scripts/run_celery_sms.sh

.PHONY: run-celery-beat
run-celery-beat: ## Run the celery beat
	./scripts/run_celery_beat.sh

.PHONY: run-celery-purge
run-celery-purge: ## Purge the celery queues
	./scripts/run_celery_purge.sh

.PHONY: run-db
run-db: ## psql to access dev database
	psql postgres://postgres:chummy@db:5432/notification_api