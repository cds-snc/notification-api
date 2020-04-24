# Notification

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



##  To run the queues 
```
scripts/run_celery.sh
```

```
scripts/run_celery_beat.sh
```

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

## Using Local Jinja for testing template changes

Jinja templates used in this repo: `email_template.jinja2`

Jinja templates are pulled in from the [notification-utils](https://github.com/cds-snc/notification-utils) repo. To test jinja changes locally (without needing to update the upstream), follow this procedure:

1. Create a `jinja_templates` folder in the project root directory. This folder name is already gitignored and won't be tracked.

2. Copy the jinja template files from [notification-utils](https://github.com/cds-snc/notification-utils) into the `jinja_templates` folder created in step 1

3. Set a new .ENV variable: `USE_LOCAL_JINJA_TEMPLATES=True`

4. Make markup changes, and see them locally!

5. When finished, copy any changed jinja files back to notification-utils, and push up the PR for your changes in that repo.

6. Remove `USE_LOCAL_JINJA_TEMPLATES=True` from your .env file, and delete any jinja in `jinja_templates`. Deleting the folder and jinja files is not required, but recommended. Make sure you're pulling up-to-date jinja from notification-utils the next time you need to make changes.

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
