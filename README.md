# Notification API

Contains:
- the public-facing REST API for Notification built on the GOV.UK Notify platform, which teams can integrate with using [their clients](https://www.notifications.service.gov.uk/documentation)
- an internal-only REST API built using Flask to manage services, users, templates, etc (this is what the [admin app](http://github.com/cds-snc/notification-admin) talks to)
- asynchronous workers built using Celery to put things on queues and read them off to be processed, sent to providers, updated, etc
  

## Functional constraints

- We currently do not support sending of letters
- We currently do not receive a response if text messages were delivered or not


## Setting Up
### Local installation instruction 

On OS X:

1. Install PyEnv with Homebrew. This will preserve your sanity. 

`brew install pyenv`

2. Install Python 3.6.9 or whatever is the latest

`pyenv install 3.6.9`

3. If you expect no conflicts, set `3.6.9` as you default

`pyenv global 3.6.9`

4. Ensure it installed by running

`python --version` 

if it did not, take a look here: https://github.com/pyenv/pyenv/issues/660

5. Install `virtualenv`:

`pip install virtualenvwrapper`

6. Add the following to your shell rc file. ex: `.bashrc` or `.zshrc`

```
export WORKON_HOME=$HOME/.virtualenvs
export PROJECT_HOME=$HOME/Devel
source  ~/.pyenv/versions/3.6.9/bin/virtualenvwrapper.sh
```

7. Restart your terminal and make your virtual environtment:

`mkvirtualenv -p ~/.pyenv/versions/3.6.9/bin/python notifications-api`

8. You can now return to your environment any time by entering

`workon notifications-api`

9. Install [Postgres.app](http://postgresapp.com/).

10. Create the database for the application

`createdb --user=postgres notification_api`

11. Decrypt our existing set of environment variables

`gcloud kms decrypt --project=[PROJECT_NAME] --plaintext-file=.env --ciphertext-file=.env.enc --location=global --keyring=[KEY_RING] --key=[KEY_NAME]`

A sane set of defaults exists in `.env.example`

12. Install all dependencies

`pip3 install -r requirements.txt`

13. Generate the version file ?!?

`make generate-version-file`

14. Run all DB migrations

`flask db upgrade`

15. Run the service

`flask run -p 6011 --host=0.0.0.0`

15a. To test

`pip3 install -r requirements_for_test.txt`

`make test`

### Pre-commit hooks

We're using [pre-commit](https://pre-commit.com/) and [talisman](https://github.com/thoughtworks/talisman)
to scan changesets for suspicious items (eg keys and secrets).

To set it up, install the required dependencies (including `pre-commit` and `go`):

```
brew bundle
```

Then initialise it, to register the git hooks:

```
pre-commit install
```

Configuration is stored in `.pre-commit-config.yaml`.

##  To run the queues 
```
scripts/run_celery.sh
```

```
scripts/run_celery_beat.sh
```

## Running in Docker
To run all the tests
`docker-compose -f ci/docker-compose-test.yml up --build --abort-on-container-exit`

To run the application and it's associated postgres instance
`docker-compose -f ci/docker-compose.yml up --build --abort-on-container-exit`

### Python version

This codebase is Python 3 only. At the moment we run 3.6.9 in production. You will run into problems if you try to use Python 3.4 or older, or Python 3.7 or newer.

## To update application dependencies

`requirements.txt` file is generated from the `requirements-app.txt` in order to pin
versions of all nested dependencies. If `requirements-app.txt` has been changed (or
we want to update the unpinned nested dependencies) `requirements.txt` should be
regenerated with

```
make freeze-requirements
```

`requirements.txt` should be committed alongside `requirements-app.txt` changes.

## Testing template changes

Jinja templates used in this repo: `email_template.jinja2`

Jinja templates are pulled in from the [notification-utils](https://github.com/cds-snc/notification-utils) repo. To test jinja changes locally without needing to push changes to notification-utils, follow this procedure:

1. Make markup changes to `email_template.jinja2` (notifications_utils/jinja_templates/email_template.jinja2)

2. (optional) Modify notifications_utils/version.py and add -SNAPSHOT to version number.
This will allow to easily revert local copy of notifications-utils in sites-packages to official version from git. 

2. From within virtual environment run:

    ```commandline
    pip install file:///path/to/notification-utils
    ```
   
3. See the changes locally!

4. Repeat steps 1, 2 and 3 until satisfied.

4. When finished run:
    ```commandline
    pip install -r requirements.txt
    ```

## Frequent problems

__Problem__ : `E999 SyntaxError: invalid syntax` when running `flake8`

__Solution__ : Check that you are in your correct virtualenv, with python 3.5 or 3.6

---

__Problem__: 
```
/bin/sh: 1: Syntax error: "(" unexpected
make: *** [Makefile:31: freeze-requirements] Error 2
```
when running `make freeze-requirements`

__Solution__: Change `/bin/sh` to `/bin/bash` in the `Makefile`

---

__Problem__: `ImportError: failed to find libmagic.  Check your installation`

__Solution__:Install `libmagic`, ex: `brew install libmagic`

---

__Problem__: `assert 'test_notification_api' in db.engine.url.database, 'dont run tests against main db`

__Solution__: Do not specify a database in your `.env`

---

__Problem__: Messages are in the queue but not sending

__Solution__: Check that `celery` is running. 
