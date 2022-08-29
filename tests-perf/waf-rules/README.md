# WAF rules overload tests

## Goals

Triggers blocking WAF rules with many users hitting sensitive endpoints many times.

## How to configure

There aren't much configuration options for these Locust tests. You can simply run these.

## How to run the WAF tests

There are two ways to run Locust, with the UI or headless.

### With the UI

Locally, simply run from the project's root:

```shell
locust -f ./tests-perf/waf-rules/locust-trigger-rate-limit.py
```

Follow the localhost address that the console will display to get to the UI. It will ask you how many total users and spawned users you want configured. Once setup, you can manually start the tests via the UI and follow the summary data and charts visually.

### Headless, via the command line

You can pass the necessary parameters to the command line to run in the headless mode. For example:

```shell
locust -f ./tests-perf/waf-rules/locust-trigger-rate-limit.py --headless --stop-timeout=10 --users=5 --html=waf-block.html
```

You can also set many of these parameters in the *locust.conf* file.
