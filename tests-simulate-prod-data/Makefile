.PHONY: help install setup generate generate-quick generate-quick-100000 generate-no-aggregates generate-notifications-and-aggregates generate-templates-only generate-live-only cleanup all

help: ## Show this help
	@grep -E '^[a-zA-Z_0-9-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-40s\033[0m %s\n", $$1, $$2}'

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

generate-quick-100000: install ## Generate all data with ~100K notifications (fast, for testing)
	python generate.py --quick-100000

generate-no-aggregates: install ## Generate data but skip ft_notification_status and ft_billing
	python generate.py --skip-aggregates

generate-notifications-and-aggregates: install ## Generate only notification_history, ft_notification_status, and ft_billing (requires existing setup)
	python generate.py --only-notifications-and-aggregates

generate-templates-only: install ## Generate only unfoldered templates for an existing service (set SERVICE_ID=<uuid>)
	@if [ -z "$(SERVICE_ID)" ]; then \
		echo "SERVICE_ID is required. Example: make generate-templates-only SERVICE_ID=d4e8a7f4-2b8a-4c9a-8b3f-9c2d4e8a7f4b"; \
		exit 1; \
	fi
	python generate.py --templates-only-service-id "$(SERVICE_ID)"

generate-live-only: install ## Generate notifications table rows only for one service/day (set SERVICE_ID=<uuid>, optional LIVE_DATE=YYYY-MM-DD)
	@if [ -z "$(SERVICE_ID)" ]; then \
		echo "SERVICE_ID is required. Example: make generate-live-only SERVICE_ID=d4e8a7f4-2b8a-4c9a-8b3f-9c2d4e8a7f4b LIVE_DATE=2026-04-29"; \
		exit 1; \
	fi
	python generate.py --live-only-service-id "$(SERVICE_ID)" $(if $(LIVE_DATE),--live-date "$(LIVE_DATE)",)

cleanup: install ## Delete all test-simulate-prod-data entities from the database
	python generate.py --cleanup-only

all: install setup generate ## Full setup: install deps, create .env, generate data
