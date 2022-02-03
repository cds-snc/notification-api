# Individual email stress test

## Goals

The goal of this code is to load test the api with individual emails.

## How to configure

Requires environment variables:
```
PERF_TEST_DOMAIN=https://...
PERF_TEST_AUTH_HEADER="apikey-v1 xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
PERF_TEST_EMAIL_TEMPLATE_ID=xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

Note that the code (`individual-emails.py`) is configured to have each user send approximately 200 emails per minute.

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
locust -f ./individual-emails.py --headless --users=5 --html=k8s_1000.html
```

You can also modify the *locust.config* file to enable the headless mode and define the necessary users, spawn rate and run time.
