# Tier 2 SMS Performance Tests

Performance tests for the **Tier 2 cost-recovery beta** (10M SMS/year, 1,500 SMS/day, 10,000 emails/day per service).

These tests are **run on-demand only** — they are not part of the nightly performance suite.

## Simulated Recipients

All tests use simulated recipients that notification-api recognises and skips real delivery for:

| Type  | Address                                       |
|-------|-----------------------------------------------|
| SMS   | `+16132532222`                                |
| Email | `simulate-delivered@notification.canada.ca`   |

## Folder Structure

```
tests-perf-tier2/
├── config.py                          # Shared config (env vars, API key pool)
├── utils.py                           # Shared helpers (auth headers, JSON builders)
├── .env.example                       # Template for required env vars
│
├── layer1_api_ceiling/                # API throughput ceiling (no real delivery)
│   ├── locust_api_throughput.py       # Staircase ramp, measures max RPS
│   └── locust.conf
│
├── layer2_single_service/             # Single Tier 2 service, full pipeline
│   ├── locust_daily_limit.py          # Sends 1,500 SMS, verifies 429 on overage
│   ├── locust_burst_sms.py            # Burst 1,500 SMS as fast as possible
│   ├── locust_mixed_workload.py       # 1,500 SMS + 10,000 emails concurrently
│   └── locust.conf
│
├── layer3_multi_service/              # N services sending concurrently
│   ├── locust_multi_service.py        # Each Locust user = different service
│   └── locust.conf
│
└── sql/
    └── tier2_results_query.sql        # Post-test e2e delivery time analysis
```

## Prerequisites

1. **Python dependencies** — Locust + python-dotenv:
   ```bash
   pip install locust python-dotenv
   ```

2. **Staging services** — Create test service(s) with:
   - `sms_daily_limit = 1500`
   - `sms_annual_limit = 10000000` (Tier 2)
   - An SMS template (and email template for mixed workload test)
   - A live API key

3. **Environment variables** — Copy `.env.example` to `.env` and fill in values.

4. For **Layer 3**, create multiple services and add all API keys to `PERF_TEST_API_KEYS` (comma-separated).

## Running the Tests

### Layer 1 — API Throughput Ceiling

Measures how many SMS API requests/second the app server can handle before latency degrades.  Uses simulated numbers so no real Pinpoint calls are made.

```bash
cd layer1_api_ceiling
locust -f locust_api_throughput.py --run-time=20m
```

The staircase shape starts at 10 users, adds 10 every 2 minutes.  Override with:
```bash
locust -f locust_api_throughput.py --start-users=20 --step-users=20 --step-time=60
```

**Watch for:** RPS plateau, p99 latency spike, error rate increase.

### Layer 2 — Single Service Tests

#### 2a: Daily Limit Verification
```bash
cd layer2_single_service
locust -f locust_daily_limit.py --run-time=30m --users=1
```
Sends SMS one-by-one. Stops automatically after confirming 429s.

#### 2b: Burst Test
```bash
locust -f locust_burst_sms.py --run-time=10m --users=25
```
Sends 1,500 SMS as fast as possible. Measures burst throughput and Celery queue absorption.

#### 2c: Mixed Workload
```bash
locust -f locust_mixed_workload.py --run-time=30m --users=10
```
Requires `PERF_TEST_EMAIL_TEMPLATE_ID`. Sends SMS and emails at the 13:87 ratio matching daily limits.

### Layer 3 — Multi-Service Concurrent Load

Requires multiple API keys in `PERF_TEST_API_KEYS`.

```bash
cd layer3_multi_service
locust -f locust_multi_service.py --run-time=20m --start-services=5 --step-services=5
```

The staircase adds 5 services every 2 minutes.  The test will cap at the number of API keys available.

**Watch for:** SQS queue depth, Celery pod CPU, Pinpoint throttle errors, DB connection saturation.

## Post-Test Analysis

Run `sql/tier2_results_query.sql` against the staging database to get per-notification-type p50/p95/p99 delivery times.

## Key Metrics

| Metric                        | Tool                    | Target          |
|-------------------------------|-------------------------|-----------------|
| API p99 latency               | Locust stats            | < 2s            |
| SMS end-to-end delivery time  | SQL query               | < 60s           |
| SQS `send-sms-*` queue depth | CloudWatch              | < 10,000        |
| Celery task failure rate      | CloudWatch / StatsD     | < 0.1%          |
| Pinpoint throttle count       | CloudWatch              | 0               |
| HTTP 429 (daily limit)        | Locust stats            | Expected at cap |
| HTTP 5xx                      | Locust stats            | 0               |

## System Limits Reference

| Parameter                  | Value         | Source                       |
|----------------------------|---------------|------------------------------|
| SMS daily limit (Tier 2)   | 1,500         | `DEFAULT_SMS_DAILY_LIMIT`    |
| Email daily limit          | 10,000        | `service.message_limit`      |
| SMS annual limit (Tier 2)  | 10,000,000    | Beta target                  |
| Celery SMS rate limit      | 1/s per worker| `CELERY_DELIVER_SMS_RATE_LIMIT` |
| SMS workers (prod)         | ~92 msg/s max | 4 workers × (3+20) pods     |
