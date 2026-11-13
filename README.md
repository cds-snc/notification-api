# Notification

Contains:
- the public-facing REST API for Notification  built on the GOV.UK Notify platform, which teams can integrate with using [their clients](https://www.notifications.service.gov.uk/documentation)
- an internal-only REST API built using Flask to manage services, users, templates, etc (this is what the [admin app](http://github.com/cds-snc/notification-admin) talks to)
- asynchronous workers built using Celery to put things into queues and read them off to be processed, sent to providers, updated, etc


## Functional constraints

- We currently do not support sending of letters
- We currently do not receive a response if text messages were delivered or not

### Inline email images (API only)

`FF_ENABLE_INLINE_IMAGES` defaults to `False`. When enabled on the API and email
workers, and the service ID is in `INLINE_IMAGE_SERVICE_IDS`,
`/v2/notifications/email` accepts PNG and JPEG images in
personalisation:

```json
{
  "email_address": "recipient@example.ca",
  "template_id": "your-template-uuid",
  "personalisation": {
    "usage_chart": {
      "file": "<base64-encoded image bytes>",
      "filename": "chart.png",
      "sending_method": "inline",
      "alt_text": "Your usage increased from 10 to 15 units."
    }
  }
}
```

Put `((usage_chart))` on its own line in the email body. Image placeholders cannot
be used in the subject, links, or conditionals. Alt text is required (1 to 1000
characters) and is used in the plain-text email and API content responses.
Arbitrary HTML remains disabled.

Set `INLINE_IMAGE_SERVICE_IDS` on both API and email workers to a comma-separated
list of permitted service IDs, for example `uuid-one,uuid-two`. Spaces around
entries are trimmed; an unset or empty list permits no services. Both the flag
and list membership are required, in addition to `upload_document` permission.
Unlisted services receive HTTP 403 before uploads. Eligibility is rechecked at
delivery, so removing a service also blocks its queued inline-image sends.
Environment values are read at process startup; restart/roll out pods after
changing them. Ordinary attachments are unaffected.

Images fit the email content width by default. Add `"display_size": "original"`
beside `"alt_text"` to request native pixel dimensions without the responsive
width constraint. `"responsive"` explicitly selects the default. Original-size
images may overflow, be clipped, or be scaled by the recipient's email client;
horizontal scrolling is not guaranteed.

Alternatively, set `"max_width": 1200` to limit the image width to 1200 pixels
while preserving its aspect ratio and without enlarging smaller images.
`max_width` must be a positive integer in pixels. Do not combine it with
`display_size`; requests specifying both are rejected.

The service needs the existing `upload_document` permission. Images share the
existing attachment count and size limits and use the document service's `attach`
storage and malware scanning. No public image hosting or new document-service
sending method is needed. A failed scan or download prevents image delivery;
pending scans use the existing retry flow. Normal attachments can coexist with
inline images. Some email clients may still show embedded images as attachments.

This local proof of concept uses a `notification-utils` wheel backported onto
53.3.0, retaining Flask 2 compatibility. The API dependency points to the generated
wheel in `local_dependencies/` (gitignored); Docker copies it before installing
dependencies. Nothing needs to be pushed to GitHub. From the API repository,
rebuild it after changing the local renderer:

```sh
(cd ../notification-utils && poetry build --format wheel)
mkdir -p local_dependencies
cp ../notification-utils/dist/notifications_utils-53.3.0+inline.3-py3-none-any.whl local_dependencies/
poetry lock --no-update
poetry install
docker build -f ci/Dockerfile -t notification-api:inline-images-local .
```

Bump the local renderer version and update the wheel path before rebuilding
changed source, then re-lock so its recorded hash matches. Deploy the same
image to the API and email workers, and set `FF_ENABLE_INLINE_IMAGES=true` in
both, and configure `INLINE_IMAGE_SERVICE_IDS` in both environments. This local wheel must be replaced with a released dependency before merging
or using the normal CI build, since it is not committed.

Disabling the flag also blocks queued inline-image sends
(they follow the normal delivery retry/failure flow). Admin image editing and
browser previews are not part of this API-first implementation.


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

4. Ensure your host `~/.aws/config` contains the `notify-staging` AWS SSO profile, then in VS Code run "Remote-Containers: Open Folder in Container..." and select this repository folder. Rebuild and reopen the devcontainer after adding or changing the profile so the updated configuration is mounted into the container.

5. *(Optional)* If you already have the vs-code-agent-feedback repository checked out locally and want it mounted inside the container, copy [.devcontainer/devcontainer.local.example.json](.devcontainer/devcontainer.local.example.json) to a new file named devcontainer.local.json inside the same folder, adjust the `source` path if needed, and reopen the devcontainer. The mount will only be applied when that local override file exists.

6. Find and update the .env file from the root of your workspace. Copy and paste the contents of the ***api .env*** item from the ***CDS Platform - Notify Local*** vault in 1password


7. Run the service

`make run`

The API and local worker targets log in with the `notify-staging` AWS SSO profile by default. For CI environments that provide AWS credentials directly, use `make run-ci` and `make run-celery-local-filtered-ci`; these targets do not run SSO login and unset `AWS_PROFILE` so the AWS SDK uses the environment credentials.


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
