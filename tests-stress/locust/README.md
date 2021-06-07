# Stress tests manual

This manual is meant for the Locust stress tests located in the same folder than this README.

## Goals

The following goals are meant with the stress-tests:

* Monitor behavior of a production-like environment under similar stress.
* Preemptively discover technical issues by overloading our staging environment.
* Fix discovered issues in the production-like environment and propagate to production.

Our stress-tests can also act as load-tests that are ran against our build pipeline in a daily manner at minimum:

* Ensure our system can take the expected daily traffic of notifications that we receive.
* Align and certify our SLA/SLO/SLI agreements negotiated with our clients.
* Discover regressions related to performance that new changes can affect on our code base and infrastructure.

## How to configure the stress tests

There is an override system that [Locust implements with configuration parameters](https://docs.locust.io/en/stable/configuration.html). It can read values from the command-line, environment variables or custom configuration file. The order is, as defined by its own documnentation:

```doc
~/locust.conf -> ./locust.conf -> (file specified using --conf) -> env vars -> cmd args
```

The current directory has a *locust.conf* file where default configuration values are defined.

Note that the `host` value can also be defined within the `User` classes such as found in the `locust-notifications.py` file. This overriden value from its parent is the default values but will be overriden by the enumerated mechanism above.

You should not have to modify the configuration to run the stress-tests locally.

## How to run the stress tests

There are two ways to run Locust, with the UI or headless.

### With the UI

Locally, simply run:

```shell
locust -f .\locust-notifications.py
```

Follow the localhost address that the console will display to get to the UI. It will ask you how many total users and spawned users you want configured. Once setup, you can manually start the tests via the UI and follow the summary data and charts visually.

### Headless, via the command line

You can pass the necessary parameters to the command line to run in the headless mode. For example:

```shell
locust -f .\locust-notifications.py --headless --users=5500 --spawn-rate=200 --run-time=10m
```

You can also modify the *locust.config* file to enable the headless mode and define the necessary users, spawn rate and run time.
