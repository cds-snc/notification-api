# Internal stress test

## Goals

The goal of this code is to test Notify internals by putting as many emails or sms as possible through the code up to the point of handing to AWS for delivery.

## How to configure

Run the setup.sh to install the python pre-requisites or run in the repo devcontainer.

Default configuration is in the `locust.conf` file.

The python file `internal_stress_test.py` requires environment variables `API_KEY`, `EMAIL_TEMPLATE_ID`, and `SMS_TEMPLATE_ID`. The template should have no variables.

```
API_KEY=gcntfy-notAKey-f6c7cc49-b5b7-4e67-a8ff-24f34be34523-f6c7cc49-b5b7-4e67-a8ff-24f34be34523
EMAIL_TEMPLATE_ID=f6c7cc49-b5b7-4e67-a8ff-24f34be34523
SMS_TEMPLATE_ID=f6c7aa49-b5b7-4e67-a8ff-24f34be34523
```
These can be in a `.env` file in the internal_stress_test directory.

__See Last Pass note "Soak Test Staging API Key and Template" in Shared-New-Notify-Staging folder__

Note that the default configuration in `locust.conf` is to send one email per second.

## How to run

There are two ways to run Locust, with the UI or headless.

### With the UI

Locally, simply run:

```shell
locust -f ./internal_stress_test.py --type [ email | sms ]
```

Follow the localhost address that the console will display to get to the UI. It will ask you how many total users and spawned users you want configured. Once setup, you can manually start the tests via the UI and follow the summary data and charts visually.

### Headless, via the command line

You can pass the necessary parameters to the command line to run in the headless mode. For example:

```shell
locust -f ./internal_stress_test.py --headless --type [ email | sms ]
```

The defaults in `locust.conf` may be overridden by command line options.