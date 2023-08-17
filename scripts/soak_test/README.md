# Soak test

## Goals

The goal of this code is to do a soak test of api while we make significant application or infrastructure changes.

There are two soak tests here:
- `soak_test_send_email.py` will POST an email to api every second.
- `soak_test_all_servers.py` will do a GET to all our servers (admin, api, dd-api, api-k8s, documentation), on average hitting each server once a second

## How to configure

Run the setup.sh to install the python pre-requisites or run in the repo devcontainer.

Default configuration is in the `locust.conf` file.

The python file `soak_test_send_email.py` requires environment variables `API_KEY` and `EMAIL_TEMPLATE_ID`. The template should have no variables.

```
API_KEY=gcntfy-notAKey-f6c7cc49-b5b7-4e67-a8ff-24f34be34523-f6c7cc49-b5b7-4e67-a8ff-24f34be34523
EMAIL_TEMPLATE_ID=f6c7cc49-b5b7-4e67-a8ff-24f34be34523
```
These can be in a `.env` file in the soak_test directory.

__See Last Pass note "Soak Test Staging API Key and Template" in Shared-New-Notify-Staging folder__

Note that the default configuration in `locust.conf` is to send one email per second.

You can supply a `--ref` option to `soak_test_send_email.py` that will set the notification's `client_reference`. This is useful in testing that all POSTs were processed successfully.

## How to run

There are two ways to run Locust, with the UI or headless.

### With the UI

Locally you can run the email soak test with:

```shell
locust -f ./soak_test_send_email.py --ref=soak-2023-05-30-A
```

Follow the localhost address that the console will display to get to the UI. It will ask you how many total users and spawned users you want configured. Once setup, you can manually start the tests via the UI and follow the summary data and charts visually.

The server soak test can be run with

```shell
locust -f ./soak_test_all_servers.py
```

### Headless, via the command line

You can pass the necessary parameters to the command line to run in the headless mode. For example:

```shell
locust -f ./soak_test_send_email.py --headless --ref=soak-2023-05-30-A
```

The defaults in `locust.conf` may be overridden by command line options

The server soak test can be run with

```shell
locust -f ./soak_test_all_servers.py --headless
```

## Checking if all emails were sent

To check whether all the POSTs from `soak_test_send_email.py` made it into the database, run the "Soak test" query on blazer. The query is already in staging, or you can run:

```sql
WITH
data as (
    select 
        n.created_at, n.sent_at, n.updated_at, client_reference, notification_status as status, t.process_type as priority
    from notifications n join templates t on n.template_id = t.id
    where client_reference like concat('%', 'soak-2023-05-30-A'::text, '%')
),
munged as (
    select *,
    EXTRACT(epoch FROM updated_at - created_at) as total_time
    from data
),
stats as (
    select 
        status, count(*),
        percentile_cont(0.5) within group(order by total_time) AS total_median,
        avg(total_time) as total_mean
    from munged
    group by status
)
select * from stats 
```

