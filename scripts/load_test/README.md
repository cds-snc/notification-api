# Soak test

## Goals

The goal of this code is to do a realistic load test of api while we make significant application or infrastructure changes.

## How to configure

Run the setup.sh to install the python pre-requisites or run in the repo devcontainer.

Default configuration is in the `locust.conf` file.

The python file `load_test.py` requires environment variables as listed in `.env.example`. The templates should have no variables.

__See One Password note "Load Test Variables" in Shared-New-Notify-Staging folder__


## How to run

There are two ways to run Locust, with the UI or headless.

### With the UI

Locally you can run the email soak test with:

```shell
locust -f ./load_test.py
```

Follow the localhost address that the console will display to get to the UI. It will ask you how many total users and spawned users you want configured. Once setup, you can manually start the tests via the UI and follow the summary data and charts visually.

### Headless, via the command line

You can pass the necessary parameters to the command line to run in the headless mode. For example:

```shell
locust -f ./load_test.py --headless
```

The defaults in `locust.conf` may be overridden by command line options

