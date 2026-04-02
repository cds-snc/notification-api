# Project Guidelines

## Code Style
- Follow existing Python style and keep changes focused; avoid unrelated refactors.
- Keep queue and task naming aligned with existing constants in [app/config.py](app/config.py).
- Prefer extending existing task and routing flows rather than introducing parallel pathways.

## Architecture
- This repository contains a Flask API plus Celery workers for async processing and provider delivery.
- Message queue taxonomy, priority mapping, and delivery queue names are centralized in [app/config.py](app/config.py).
- Notification creation and queue triage paths are implemented in [app/v2/notifications/post_notifications.py](app/v2/notifications/post_notifications.py).
- Provider dispatch and retry/failure handling are implemented in [app/celery/provider_tasks.py](app/celery/provider_tasks.py) and [app/delivery/send_to_providers.py](app/delivery/send_to_providers.py).
- For end-to-end system flow, see [DATAFLOW.md](DATAFLOW.md). For local setup and operational basics, see [README.md](README.md).

## Build and Test
- Run API locally: `make run`
- Run Celery workers locally: `make run-celery-local`
- Run filtered Celery logs for delivery debugging: `make run-celery-local-filtered`
- Run unit/integration tests: `make test`
- Run lint/type checks and formatting: `make format`
- Run smoke tests: `make smoke-test`

## Queue and Worker Conventions
- Preserve legacy priority compatibility by respecting `Priorities.to_lmh` behavior in [app/config.py](app/config.py).
- For SMS and email routing, use message-type delivery queues from `QueueNames.DELIVERY_QUEUES`; do not mix message types on generic workers.
- Preserve existing retry and failure semantics in [app/celery/provider_tasks.py](app/celery/provider_tasks.py), especially for `deliver_sms` and `deliver_throttled_sms`.
- SMS-focused worker startup pattern should remain queue-scoped as shown in [scripts/run_celery_send_sms.sh](scripts/run_celery_send_sms.sh).

## Current Delivery Initiative: SMS Control Lane
When implementing the SMS dedicated sending queue rollout, apply all of the following:

- Gate behavior end-to-end with one feature flag.
  - Flag off: preserve current behavior.
  - Flag on: route all prepared SMS through the control-lane queue path.
- Ensure prepared SMS notifications are routed only to SMS-specific queue path(s), not mixed message-type Celery workers.
- Ensure SMS preparation workers consume only SMS lane queues.
- Enforce throughput limits for sending.
- Preserve existing failure and retry behavior during the rollout.

Implementation references in this repo:
- Queue taxonomy and routing baseline: [app/config.py](app/config.py), [app/v2/notifications/post_notifications.py](app/v2/notifications/post_notifications.py)
- SMS worker queue pattern: [scripts/run_celery_send_sms.sh](scripts/run_celery_send_sms.sh)
- SMS provider dispatch and retry behavior: [app/celery/provider_tasks.py](app/celery/provider_tasks.py), [app/delivery/send_to_providers.py](app/delivery/send_to_providers.py)

Deployment and throughput configuration note:
- Helm deployments for API and Celery are managed in the separate manifests repository: https://github.com/cds-snc/notification-manifests
- Any new throughput limit setting must be configurable through manifests/Helm values and wired to runtime config in this API service.

## QA Expectations For This Initiative
- Run smoke tests and verify they pass.
- Validate SMS messages are published to SMS-specific queue path(s).
- Validate SMS preparation workers do not consume non-SMS queues.
- Validate feature-flag-off behavior remains compatible with both old and new paths.