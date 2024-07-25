# Individual email stress test

## Goals

The goal of this code is to load test the api with individual emails.

## How to configure

Some test configuration is in the `locust.conf` file.

The python file `individual-emails.py` requires these environment variables:
```
PERF_TEST_AUTH_HEADER="apikey-v1 xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
PERF_TEST_EMAIL_TEMPLATE_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

Note that `individual-emails.py` is configured to have each user send 1 email per second.

You can supply a `--ref=test` option (defined in `individual-emails.py`) that will set a prefix for the notification's `client_reference`. This is useful in testing that all POSTs were processed successfully.]

Note that there are three tasks that can be run, `send_email()`, `send_email_with_file_attachment()`, and `send_email_with_5_file_attachments()`. Set the task weights as desired (including setting some to zero to not run that task)

## How to run

There are two ways to run Locust, with the UI or headless.

### With the UI

Locally, simply run:

```shell
poetry run locust -f ./individual-emails.py
```

Follow the localhost address that the console will display to get to the UI. It will ask you how many total users and spawned users you want configured. Once setup, you can manually start the tests via the UI and follow the summary data and charts visually.

### Headless, via the command line

You can pass the necessary parameters to the command line to run in the headless mode. For example:

```shell
poetry run locust -f ./individual-emails.py --headless  --stop-timeout=10 --host=https://api.staging.notification.cdssandbox.xyz --run-time=10m --users=5 --ref=load-test
```

You can also set many of these parameters in the *locust.conf* file.

To check send times you can run the a blazer query such as

```sql
WITH
    ref AS (VALUES ('load-test')),
email_initial_data as (
    select 
        n.created_at, n.sent_at, n.updated_at, client_reference, notification_status as status, t.process_type as priority
    from notifications n join templates t on n.template_id = t.id
    where client_reference like concat('%', (table ref), '%')
),
email_data as (
    select *,
    EXTRACT(epoch FROM updated_at - created_at) as total_time,
    from email_initial_data
),
email_stats as (
    select 
        status, count(*),
        percentile_cont(0.5) within group(order by total_time) AS total_median,
        avg(total_time) as total_mean
    from email_data
    group by  status
)
select * from email_stats
```
