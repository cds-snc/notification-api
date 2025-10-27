# Notification

Contains:
- the public-facing REST API for Notification  built on the GOV.UK Notify platform, which teams can integrate with using [their clients](https://www.notifications.service.gov.uk/documentation)
- an internal-only REST API built using Flask to manage services, users, templates, etc (this is what the [admin app](http://github.com/cds-snc/notification-admin) talks to)
- asynchronous workers built using Celery to put things into queues and read them off to be processed, sent to providers, updated, etc


## Functional constraints

- We currently do not support sending of letters
- We currently do not receive a response if text messages were delivered or not


## Setting Up

For any issues during the following instructions, make sure to review the
**Frequent problems** section toward the end of the document.

### Local installation instruction (Use Dev Containers)
#### In a [VS Code devcontainer](https://code.visualstudio.com/docs/remote/containers-tutorial)

1. Install VS Code

`brew install --cask visual-studio-code`

2. Install Docker

`brew install --cask docker`

3. Install the [Remote-Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers)

4. In VS Code run "Remote-Containers: Open Folder in Container..." and select this repository folder

5. Find and update the .env file from the root of your workspace. Copy and paste the contents of the ***api .env*** item from the ***CDS Platform - Notify Local*** vault in 1password

6. Run the service

`make run`


##  To run the queues

Run `make run-celery-local` or `make run-celery-local-filtered`. Note that the "filtered" option does not show the beat worker logs nor most scheduled tasks (this makes it easier to trace notification sending).

### Python version

This codebase is Python 3 only. At the moment we run 3.12.7 in production. You will run into problems if you try to use Python 3.4 or older.

### To run Performance tests

Ask your teamate for the following keys and add to .env
```
PERF_TEST_AUTH_HEADER =
PERF_TEST_BULK_EMAIL_TEMPLATE_ID=
PERF_TEST_EMAIL_WITH_LINK_TEMPLATE_ID=
PERF_TEST_EMAIL_TEMPLATE_ID=
PERF_TEST_EMAIL_WITH_ATTACHMENT_TEMPLATE_ID=
PERF_TEST_SMS_TEMPLATE_ID =
```

And run the performance tests using. We generally test with 3000 users every 20 seconds (but use your best judgement).
```
locust -f tests-perf/locust/locust-notifications.py
```

## To update application dependencies

`poetry.lock` file is generated from the `pyproject.toml` in order to pin
versions of all nested dependencies. If `pyproject.toml` has been changed (or
we want to update the unpinned nested dependencies) `poetry.lock` should be
regenerated with

```
poetry lock --no-update
```

`poetry.lock` should be committed alongside `pyproject.toml` changes.

## Using Local Jinja for testing template changes

Jinja templates used in this repo: `email_template.jinja2`

Jinja templates are pulled in from the [notification-utils](https://github.com/cds-snc/notification-utils) repo. To test jinja changes locally (without needing to update the upstream), follow this procedure:

1. Create a `jinja_templates` folder in the project root directory. This folder name is already gitignored and won't be tracked.

2. Copy the jinja template files from [notification-utils](https://github.com/cds-snc/notification-utils) into the `jinja_templates` folder created in step 1

3. Set a new .ENV variable: `USE_LOCAL_JINJA_TEMPLATES=True`

4. Make markup changes, and see them locally!

5. When finished, copy any changed jinja files back to notification-utils, and push up the PR for your changes in that repo.

6. Remove `USE_LOCAL_JINJA_TEMPLATES=True` from your .env file, and delete any jinja in `jinja_templates`. Deleting the folder and jinja files is not required, but recommended. Make sure you're pulling up-to-date jinja from notification-utils the next time you need to make changes.

## Testing

To help debug full code paths of emails and SMS, we have a special email and phone number
set in the application's configuration. As it stands at the moment these are the following:

| Notification Type | Test destination         |
| ----------------- | ------------------------ |
| Email             | internal.test@cds-snc.ca |
| SMS               | +16135550123             |

Whereas the smoke test emails and long codes might not get through the whole GCNotify
data treatment, these will and have proper database fields populated. This is useful
for proper stress tests where the notifications shouldn't merely touch the API 
front-door but also get through the Celery workers processing.

## Frequent problems

__Problem__: No *postgres* role exists.

__Solution__: If the command complains you don't have a *postgres* role existing,
execute the following command and retry the above afterward:

```
createuser -l -s postgres
```

__Problem__ : `E999 SyntaxError: invalid syntax` when running `flake8`

__Solution__ : Check that you are in your correct virtualenv, with python 3.12

---

__Problem__: `ImportError: failed to find libmagic.  Check your installation`

__Solution__:Install `libmagic`, ex: `brew install libmagic`

---

__Problem__: `assert 'test_notification_api' in db.engine.url.database, 'dont run tests against main db`

__Solution__: Do not specify a database in your `.env`

---

__Problem__: `sqlalchemy.exc.OperationalError: (psycopg2.OperationalError) fe_sendauth: no password supplied`

__Solution__: Ensure `SQLALCHEMY_DATABASE_URI` supplied in pytest.ini or your `.env` file is valid to your
local database with user access, (pytest.ini takes precedence)

---

__Problem__: Messages are in the queue but not sending

__Solution__: Check that `celery` is running.
