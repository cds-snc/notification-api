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

You can supply a `--ref=test` option (defined in `individual-emails.py`) that will set a prefix for the notification's `client_reference`. This is useful in testing that all POSTs were processed successfully.
## How to run

There are two ways to run Locust, with the UI or headless.

### With the UI

Locally, simply run:

```shell
locust -f ./individual-emails.py
```

Follow the localhost address that the console will display to get to the UI. It will ask you how many total users and spawned users you want configured. Once setup, you can manually start the tests via the UI and follow the summary data and charts visually.

### Headless, via the command line

You can pass the necessary parameters to the command line to run in the headless mode. For example:

```shell
locust -f ./individual-emails.py --headless --stop-timeout=10 --host=https://api-k8s.staging.notification.cdssandbox.xyz --users=5 --html=k8s_1000.html
```

You can also set many of these parameters in the *locust.conf* file.

