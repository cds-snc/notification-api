# Load testing

We can run load tests using [Locust](https://docs.locust.io/en/stable/index.html).

In `./load_testing`, run:

`pip install -r requirements.txt`

Set the following environment variables - the service ID, template ID, and API Key to be used
in the environment of choice.

```shell
LOAD_TESTING_{environment}_template_id
LOAD_TESTING_{environment}_service_id
LOAD_TESTING_{environment}_api_key
```

For example, if we're hitting `https://dev.api.notifications.va.gov`:

```shell
LOAD_TESTING_dev_service_id={id of the service configured in dev}
```

You can use [`direnv`](https://direnv.net/) to set these environment variables:

```shell
cp .envrc.example .envrc
direnv allow
```

Now, run Locust with the following command:

```shell
locust -f locustfile.py -u 1 -r 1 --run-time 10s --host https://dev.api.notifications.va.gov --headless
```
