.PHONY: help install setup generate generate-quick generate-no-aggregates cleanup all

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install Python dependencies
	pip install -r requirements.txt

setup: ## Copy .env.example to .env (if .env doesn't exist)
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo ".env created from .env.example — edit SQLALCHEMY_DATABASE_URI before running."; \
	else \
		echo ".env already exists — skipping."; \
	fi

generate: install ## Generate all production-like data (full run: ~14M notifications)
	python generate.py

generate-quick: install ## Generate everything except notification_history (fast, for testing setup)
	python generate.py --skip-notifications

generate-no-aggregates: install ## Generate data but skip ft_notification_status and ft_billing
	python generate.py --skip-aggregates

cleanup: install ## Delete all test-simulate-prod-data entities from the database
	python generate.py --cleanup-only

all: install setup generate ## Full setup: install deps, create .env, generate data
