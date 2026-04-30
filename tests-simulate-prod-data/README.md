# tests-simulate-prod-data

Generate non-PII, production-like data in a staging database for performance testing.

## What it creates

| Entity | Count | Details |
|---|---|---|
| Organisation | 1 | `test-simulate-prod-data-org` |
| Service | 1 | `test-simulate-prod-data-service` with prod-like limits (10M SMS, 25M email annual) |
| Users | 5 | `test-simulate-prod-data-user-{1..5}@staging-simulate.local`, blocked (no login), full permissions including folder access |
| Reply-to address | 1 | Default reply-to for the service |
| Template folders | 5 | 1 high-volume folder + 4 regular folders (all users have access to all folders) |
| Templates | ~2,020 | 2,000 in the high-volume folder (mix of email/sms, with 3-5 `{{variables}}`), ~5 each in others |
| Templates history | ~2,020 | Matching version 1 entries for all templates |
| Jobs | 200 | Simulated bulk send jobs (status: finished) |
| Notification history (email) | 5,000,000 | 4,950,000 delivered + 50,000 permanent-failure |
| Notification history (SMS) | 9,000,000 | 8,910,000 delivered + 90,000 permanent-failure |
| Live notifications | 1,000,000 | Recent notifications in the `notifications` table (last 7 days, mix of statuses) |
| ft_notification_status | ~1,460 rows | Daily aggregates for the fiscal year |
| ft_billing | ~730 rows | Daily billing aggregates for the fiscal year |

All data is spread across the configurable date range (default: fiscal year Apr 2025 – Mar 2026).

## Prerequisites

```bash
make install
```

## Configuration

Copy the example env file and edit as needed:

```bash
make setup
```

**Required:** `SQLALCHEMY_DATABASE_URI` — the PostgreSQL connection string for the target database.

All other values have sensible defaults. See [.env.example](.env.example) for the full list.

### Key configuration options

| Variable | Default | Description |
|---|---|---|
| `SQLALCHEMY_DATABASE_URI` | _(required)_ | PostgreSQL connection string |
| `DATE_START` | `2025-04-01` | Start of the notification date range |
| `DATE_END` | `2026-03-31` | End of the notification date range |
| `NUM_EMAILS_TOTAL` | `5000000` | Total email notifications to generate |
| `NUM_EMAILS_FAILED` | `50000` | Email notifications with permanent-failure status |
| `NUM_SMS_TOTAL` | `9000000` | Total SMS notifications to generate |
| `NUM_SMS_FAILED` | `90000` | SMS notifications with permanent-failure status |
| `NUM_LIVE_NOTIFICATIONS` | `1000000` | Recent notifications in the live `notifications` table |
| `BATCH_SIZE` | `10000` | Rows per batch insert (tune for your DB) |

## Usage

### Generate data

```bash
cd tests-simulate-prod-data
make generate
```

#### Useful flags

```bash
# Skip the 14M notification_history rows (fast — just creates service/users/templates/jobs)
make generate-quick

# Generate all data with ~185K notifications (fast, for testing the full flow)
# Uses preset: 95.5K emails + 90K SMS + 10K live notifications
make generate-quick-100000

# Create only unfoldered templates for an existing service UUID
make generate-templates-only SERVICE_ID=d4e8a7f4-2b8a-4c9a-8b3f-9c2d4e8a7f4b

# Create live notifications only (notifications table), for one service on one UTC day
# Counts come from NUM_EMAILS_TOTAL / NUM_SMS_TOTAL in .env (or inline overrides)
NUM_EMAILS_TOTAL=900000 NUM_SMS_TOTAL=600000 make generate-live-only SERVICE_ID=d4e8a7f4-2b8a-4c9a-8b3f-9c2d4e8a7f4b LIVE_DATE=2026-04-29

# Skip aggregate tables (ft_notification_status, ft_billing)
make generate-no-aggregates

# Generate only notifications and aggregates (requires existing setup objects from previous run)
make generate-notifications-and-aggregates
```

### Cleanup (delete all generated data)

```bash
make cleanup
```

### Full setup + generate (install, create .env, generate data)

```bash
make all
```

This finds all entities with the `test-simulate-prod-data` prefix and deletes them in the correct FK order.

## How it works

1. **No PII** — All email addresses use `@staging-simulate.local`, phone numbers use a test number (`+16135550199`). No real user data is created.
2. **Direct SQL** — Uses SQLAlchemy Core with raw parameterised SQL for maximum insert speed. The 14M notification rows are inserted in configurable batches (default 10K).
3. **Realistic distribution** — Notifications are randomly spread across the date range. ~70% of notifications are linked to job records. Templates contain 3-5 placeholder variables.
4. **Idempotent cleanup** — The `--cleanup-only` flag removes everything by prefix, so you can re-run safely.

## Performance notes

- Inserting 14M rows takes significant time. Expect ~30-60 minutes depending on DB performance.
- Increase `BATCH_SIZE` (e.g., 50000) on powerful staging DBs for faster inserts.
- Use `--skip-notifications` to quickly test the setup logic before doing a full run.
- Consider running inside a `screen` or `tmux` session for long runs.

## Relationship to tests-perf

This script populates the **database** with realistic data volumes. After running it, use the existing [tests-perf/](../tests-perf/) Locust scripts to run performance tests against the API with this data in place. The combination tests both API throughput and database query performance under realistic conditions.
