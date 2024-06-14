.DEFAULT_GOAL := help
SHELL := /bin/bash
DATE = $(shell date +%Y-%m-%d:%H:%M:%S)

APP_VERSION_FILE = app/version.py

GIT_BRANCH ?= $(shell git symbolic-ref --short HEAD 2> /dev/null || echo "detached")
GIT_COMMIT ?= $(shell git rev-parse HEAD)

help:
	@cat $(MAKEFILE_LIST) | grep -E '^[a-zA-Z_-]+:.*?## .*$$' | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

generate-version-file: ## Generates the app version file
	mkdir -p app
	@echo -e "__git_commit__ = '${GIT_COMMIT}'\n__time__ = '${DATE}'" > ${APP_VERSION_FILE}

test:
	./scripts/run_tests.sh
	rm -rf .pytest_cache test_results.xml

clean: ## Remove virtualenv directory and build articacts
	rm -rf node_modules cache target venv .coverage build tests/.cache

install-bandit:
	pip install bandit

check-vulnerabilities: install-bandit ## Scan code for vulnerabilities and issues
	bandit -c .bandit.yml -r app/ -l

install-safety:
	pip install safety

check-dependencies: install-safety ## Scan dependencies for security vulnerabilities
	# 12 Dec 2023: 51668 is fixed with >= 2.0.0b1 of SQLAlchemy. Ongoing refactor to upgrade.
	# 6 June 2024: 70624 will be resolved with ticket #1794
	# 6 June 2024: 70612 vulnerability found with jinja2 version 3.1.3
	# 14 June 2024: 70813 Vulnerability found in flask-cors version 4.0.0

	safety check -r poetry.lock --full-report -i 51668,70624,70612,70813

.PHONY:
	help \
	generate-version-file \
	test \
	clean \
	check-vulnerabilities \
	check-dependencies
