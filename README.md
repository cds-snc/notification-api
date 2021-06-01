# Notification API

Contains:
- the public-facing REST API for Notification built on the GOV.UK Notify platform, which teams can integrate with using [their clients](https://www.notifications.service.gov.uk/documentation)
- an internal-only REST API built using Flask to manage services, users, templates, etc (this is what the [admin app](http://github.com/cds-snc/notification-admin) talks to)
- asynchronous workers built using Celery to put things on queues and read them off to be processed, sent to providers, updated, etc
  

## Functional constraints

- We currently do not support sending of letters
- We currently do not receive a response if text messages were delivered or not
- We currently do not receive status updates from our email provider (Granicus) while waiting for ESECC process to be completed

---

## Table of Contents

- [Notification API](#notification-api)
  - [Functional constraints](#functional-constraints)
  - [Table of Contents](#table-of-contents)
  - [API Documentation](#api-documentation)
  - [Setting Up](#setting-up)
    - [Checklist](#checklist)
    - [Local installation instruction](#local-installation-instruction)
    - [Pre-commit hooks](#pre-commit-hooks)
    - [Installation for local development](#installation-for-local-development)
    - [Other useful commands](#other-useful-commands)
- [Deployment Workflow](#deployment-workflow)
- [To run the queues](#to-run-the-queues)
  - [Running in Docker](#running-in-docker)
  - [AWS Configuration](#aws-configuration)
    - [Install tools](#install-tools)
    - [Useful commands](#useful-commands)
  - [AWS Lambda Functions](#aws-lambda-functions)
  - [Terraform](#terraform)
    - [Install tools](#install-tools-1)
    - [Useful commands](#useful-commands-1)
    - [Python version](#python-version)
  - [To update application dependencies](#to-update-application-dependencies)
  - [Running Code Scans](#running-code-scans)
    - [Bandit](#bandit)
    - [Safety](#safety)
  - [Testing template changes](#testing-template-changes)
  - [Using Mountebank stubs for MPI/VAProfile](#using-mountebank-stubs)
  - [Frequent problems](#frequent-problems)

---

## API Documentation
VANotify OpenAPI specification can be downloaded [here](https://github.com/department-of-veterans-affairs/notification-api/blob/master/documents/openapi/openapi.yaml)

Postman collection and environment files are available [here](https://github.com/department-of-veterans-affairs/notification-api/tree/master/scripts/postman) 

## Setting Up

### Checklist

* Local installation in [this section](#local-installation-instruction)
  - PyEnv
  - Python
  - virtualenv
  - Postgres
  - project dependencies
  - Docker
* Install pre-commit hooks in [this section](#pre-commit-hooks)
  - pre-commit
  - talisman
* Installation for local development in [this section](#installation-for-local-development)


### Local installation instruction 

<details>

On OS X:

1. Install PyEnv with Homebrew. This will preserve your sanity. 

`brew install pyenv`

2. Install Python 3.6.10 (or whatever version is specified in .python-version)
Then follow from instructions for rest of pyenv setup, [see step 3 here](https://github.com/pyenv/pyenv#basic-github-checkout)

`pyenv install 3.6.10`

3. If you expect no conflicts, set `3.6.10` as you default

`pyenv global 3.6.10`

Note: 
- if md5 hash issue, may be related to openssl version. `brew upgrade openssl && brew switch openssl`

- problem: if can't find virtualenv.sh in current python version
`echo -e 'if command -v pyenv 1>/dev/null 2>&1; then\n  eval "$(pyenv init -)"\nfi' >> ~/.bash_profile`

```
pip install --upgrade pip
pip install --upgrade virtualenvwrapper
```

- to check Python version currently being used, run `pyenv version`

- to check list of Python versions installed, run `pyenv versions`

4. Ensure it installed by running

`python --version` 

if it did not, take a look here: https://github.com/pyenv/pyenv/issues/660

5. Install `virtualenv`:

`pip install virtualenvwrapper`

Note:
- if you update to a later Python version, you will need to repeat steps 5~7 with reference to the new version.

6. Add the following to your shell rc file. ex: `.bashrc` or `.zshrc`

```
export WORKON_HOME=$HOME/.virtualenvs
export PROJECT_HOME=$HOME/Devel
source  ~/.pyenv/versions/3.6.10/bin/virtualenvwrapper.sh
```

7. Restart your terminal and make your virtual environtment:

`mkvirtualenv -p ~/.pyenv/versions/3.6.10/bin/python notification-api`

8. You can now return to your environment any time by entering

`workon notification-api`

 Exit the virtual environment by running `deactivate`

9. Install [Postgres.app](http://postgresapp.com/).

 > Note:
    > - check version of Postgres used in `ci/docker-compose.yml` to install correct `db:image` version.
    > - If you do not have PostgresSQL installed, run `brew install postgresql`

10. Create the database for the application

`createdb --user=postgres notification_api`

11. Install all dependencies

`pip3 install -r requirements.txt`

12. Generate the version file ?!?

`make generate-version-file`

12. Create .env file

`cp .env.example .env`

> Note:
    > - You will need to get a team member to help you get appropriate values

13. Run all DB migrations

`flask db upgrade`

Note:
- For list of flask migration cli commands, see `/migrations/README.md`

14. Run the service

`flask run -p 6011 --host=0.0.0.0`

Note: When running locally, you can block all tasks from executing locally by blocking until the task returns. 
To use this, you need to set celery to always eager by setting `'task_always_eager': True` in `config.py` 
`CELERY_SETTINGS`. Do not commit this change.

14a. To test

`pip3 install -r requirements_for_test.txt`

`make test`

15. Install Docker

Visit this page to get Docker set up: [https://docs.docker.com/get-docker/](https://docs.docker.com/get-docker/)

</details>

### Pre-commit hooks

<details>

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

</details>

---

### Installation for local development

Install [LocalStack](https://github.com/localstack/localstack), which is library that mocks AWS services, including SQS (which we use to send messages), run: 
```
pip3 install -r requirements_for_local.txt
```

Set environment variables required to run LocalStack:
```
export SERVICES=sqs
export DEFAULT_REGION=us-east-2
```

To get LocalStack started, which by default will spin up a Docker container, run:
```
localstack start
```

Upon starting up LocalStack, you can visit the provided port at https://localhost:4566/. You should get

```
{"status": "running"}
```

If you have issues with LocalStack, you can downgrade to 0.11.2, run:

```
docker pull localstack/localstack:0.11.2
docker tag localstack/localstack:0.11.2 localstack/localstack:latest
```

### Other useful commands

To checks if queues are created, run:

```
AWS_ACCESS_KEY_ID=foo AWS_SECRET_ACCESS_KEY=bar aws --endpoint-url=http://localhost:{port} sqs list-queues
```

To check if messages are queued up, run:

```
AWS_ACCESS_KEY_ID=foo AWS_SECRET_ACCESS_KEY=bar aws --endpoint-url=http://localhost:{port} sqs receive-message --max-number-of-messages 10 --queue-url={queue url provided in from list-queues command}
```
* Note that the max number (n) of messages can be 1 < n <= 10

---

## Deployment Workflow

1. Ensure that the deploy to the development and staging environments passed. If that is the case, you should see a
   workflow called __Create Git and Docker Tags__ in Github Actions associated with your commit.

2. Click the __Create Git and Docker Tags__ workflow. You should see a commit hash next to _va-tw-bot_, which should
   correspond to your commit.

3. Click the __create-production-tags__ workflow. Open up the step titled __Tag Docker Image in VAEC__. The very first
   line should be something like this:
   `Run bash ./scripts/tag_docker_image.sh staging-v0.0.349 v0.0.349 us-gov-west-1`. The tag starting with "v"
   (e.g., `v0.0.349`) is the tag attached to your commit and the docker image, and you'll use it to deploy.

4. Back in Github Actions, navigate to the
   [Trigger Workflow](https://github.com/department-of-veterans-affairs/notification-api/actions/workflows/deployment-trigger.yaml)
   .

5. Click the __Run workflow__ button. For the most part, you can keep the _Use workflow from branch selection_ as
   `master`, but feel free to change it for your specific use case. For _Environment to provision_, enter the
   appropriate environment you're trying to deploy to. For _Git and docker tag_, enter the tag you obtained from the
   __Create Git and Docker Tags__ step (step 3).

6. Click the __Run workflow__ button, and you're good to go!
---

##  To run the queues 
```
scripts/run_celery.sh
```

```
scripts/run_celery_beat.sh
```
---

## Running in Docker
Make sure to copy over the .docker-env.example file and fill in the values.

When building the docker image for the first time, run `docker-compose -f ci/docker-compose-local.yml build app`

To run all the tests
`docker-compose -f ci/docker-compose-test.yml up --build --abort-on-container-exit`

To run the application and it's associated postgres instance
`docker-compose -f ci/docker-compose.yml up --build --abort-on-container-exit`

To run the app locally, with celery using localstack
`docker-compose -f ci/docker-compose-local.yml up --build`

If you're running with `docker-compose-local.yml`, and AWS SES is enabled as a provider, you may need to
run the following to give the (simulated) SES permission to (pretend to) send emails:

```
aws ses verify-email-identity --email-address stage-notifications@notifications.va.gov --endpoint-url=http://localhost:4566
```

---

## AWS Configuration
At the moment, we have our own AWS account. In order to run the application you have to be authenticated with AWS because of this AWS infrastructure setup. So the following will need to be installed.

### Install tools

<details>

```
brew install awscli
brew tap versent/homebrew-taps
brew install saml2aws
```

Upon successful installation, grab a team member. They can walk you through specific configuration for our AWS account.

</details>

### Useful commands

<details>

To export profile as env var locally, run the following. For local env persistance, can save this env var through other means (like using direnv):
```
export AWS_PROFILE={profile}
```

To check currently assumed AWS role (i.e. AWS_PROFILE value), run:
```
aws sts get-caller-identity
```

</details>

---

## AWS Lambda Functions
We house our lambda functions in `/lambda_functions/*`. The infrastructure resources live in our infra repo as part of the utility stack.

#### List of lambda functions (`/lambda_functions/*`):

* user_flows_lambda
  - Triggers user flows tests
  - lives in `/lambda_functions/user_flows/`
    
* pinpoint_callback_lambda
* pinpoint_inbound_sms_lambda
* ses_callback_lambda
* two_way_sms_lambda

#### Development workflow (suggested):
_Follow user flows lambda setup as model_

1. If creating a new lambda function, the basic assets needed are:
  - Create needed lambda resources in our infra repo, which requires a dummy lambda zip file deployed
  - Create a subdirectory in the /lambda_functions/
  - Create a file in the subdirectory using the naming convention `{function name}_lambda.py`
  - In the lambda file, it should define the handler with similar convention: `{function name}_handler(event, context)`
  - Define a new deploy job in ['Build Lambda Functions'](.github/workflows/lambda-functions.yaml) workflow following the naming convention `deploy-{functon name}-lambda`

2. Building out the lambda function:
  - Any time you make changes and push them up, the ['Build Lambda Functions'](.github/workflows/lambda-functions.yaml) workflow will be triggered, specifically related to the lambda you're working on if the deploy job was scoped correctly. This workflow packages up the required artifacts and deploys to the AWS Lambda service. Current setup does not invoke the function upon completed deployment.
  - To invoke the function, you can either use the AWS Lambda project specific console or awscli.

Resources:
* [AWS Lambda Documentation](https://docs.aws.amazon.com/lambda/index.html)

---

## Terraform
In this repository, our Terraform infrastructure files are separated into several directories. The following directories dictate the order in which `terraform init` needs to be separately run. Order is important because each directory configures resources that the next one needs. Currently, the order is:

```
1. /cd/base-infrastructure/
2. /cd/application-database/
3. /cd/application-infrastructure/
```

### Install tools

<details>

```
brew install terraform
```

</details>

### Useful commands

<details>

These might be commonly used Terraform cli commands used on this project. Check out [Terraform documentation](https://www.terraform.io/docs/cli-index.html) for more details.

To initialize the project and create a Terraform directory with remote state, run this command separately in the directories listed above:
```
terraform init
```

To validate syntatical correctness of configuration (not the Terraform state), run:
```
terraform validate
```

To do a dry-run locally for applying Terrform changes, run:
```
terraform plan
```

**WARNING: DO NOT RUN THE FOLLOWING ON LOCAL MACHINE. OUR CI IS ALREADY HANDLING THIS.**

But if you caused some issues that require running this locally, to make all the changes (add, delete, edit) to the infrastructure, run: 
```
terraform apply
```

</details>


### Python version

This codebase is Python 3 only. At the moment we run 3.6.9 in production. You will run into problems if you try to use Python 3.4 or older, or Python 3.7 or newer.

---

## To update application dependencies

`requirements.txt` file is generated from the `requirements-app.txt` in order to pin
versions of all nested dependencies. If `requirements-app.txt` has been changed (or
we want to update the unpinned nested dependencies) `requirements.txt` should be
regenerated with

```
make freeze-requirements
```

`requirements.txt` should be committed alongside `requirements-app.txt` changes.

---

## Running Code Scans
The instructions below are for running locally and are implemented as jobs in our pipeline.

### [Bandit](https://pypi.org/project/bandit/)
Scans for common security issues in Python code

```
make check-vulnerabiltiies
```

### [Safety](https://pyup.io/safety/)
Checks python dependencies for known security vulnerabilities

Note: Some of the dependencies are generated from the `utils` repo, so dependencies may need to be updated there first.

```
make check-dependencies
```

---

## Testing template changes

Jinja templates are pulled in from the [notification-utils](https://github.com/department-of-veterans-affairs/notification-utils) repo. Jinja templates used in this repo: `email_template.jinja2`. To test jinja changes locally without needing to push changes to notification-utils, follow this procedure:

1. Make markup changes to `email_template.jinja2` (notifications_utils/jinja_templates/email_template.jinja2)

2. (optional) Modify notifications_utils/version.py and add -SNAPSHOT to version number, e.g. `'version.number-SNAPSHOT'`.
This will allow to easily revert local copy of notifications-utils in sites-packages to official version from git. 

3. From within the notification-api virtual environment reinstall the utils dependency into the api repo, run:

    ```commandline
    pip install file:///path/to/notification-utils
    ```
   
4. See the changes locally! 
    - Be sure the local server for notification-api is running to send an email. 
    - Refer to section [Installation for Local Development](###installation-for-local-development) for local setup or [Running in Docker](##running-in-Docker) for Docker command to local startup.

5. Repeat steps 1, 2 and 3 until satisfied.

6. When finished run:
    ```commandline
    pip install -r requirements.txt
    ```

---

## Using Mountebank Stubs

We have some stubs set up for making requests to MPI and VA Profile located in `scripts/mountebank/stubs`. In order to
hit these, start up the app locally with Docker and make sure the mountebank container is running properly.

To hit the MPI endpoints, make a POST request to send a notification with the following information instead of the
email/phone number in the payload:

```
"recipient_identifier": {
        "id_type": "PID",
        "id_value": <id value in stub url>
},
```

The ID value in the stub url is the number after `Patient/` and before the % sign (e.g., `400400` for
`/psim_webservice/fhir/Patient/400400%5EPI%5E200CORP%5EUSVBA$`).

For the VA Profile endpoints, make the same POST request to send a notification but use the following information
instead of an email/phone number in the payload:

```
"recipient_identifier": {
        "id_type": "VAPROFILEID",
        "id_value": <id value in stub url>
},
```

The ID value in the stub url is the number after `v1/` (e.g., `2003` for `/cuf/contact-information/v1/2003/emails$`).

---

## Adding Environment Variables to Task Definition files
When adding environment variables to any `<filename>-task-definition.json` file, make sure you add them to the corresponding
`celery`and `celery-beat` files as well. We want to try and keep these consistent with each other.

___

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

---

__Problem__: Github Actions is failing when running the 'Perform twistlock scan' step of the 'build-and-push' job

__Solution__:

1. Navigate to [Twistlock UI](https://twistlock.devops.va.gov/#!/login)

2. Click Monitor -> Vulnerabilities -> Images -> CI

3. You should see your failing scan. Click on it to see what's going on. Usually the issue is due to a vulnerability
   that will be fixed soon in the alpine linux version that we're using; Twistlock will tell you the version with the
   fix if applicable.

4. If there is a fix, we can just ignore the Twistlock alert for a week because our alpine linux version will probably
   update to have the fix soon. Go to Defend -> Vulnerabilities -> CI to pull up the Vulnerability Rules.

5. Click on the existing Rule and scroll down to Exceptions. You can add your exception and set the expiration date to a
   week from now.

---

__Problem__: `./Modules/posixmodule.c:10432:5: warning: code will never be executed [-Wunreachable-code]
Py_FatalError("abort() called from Python code didn't abort!");`

This error may occur while attempting to install pyenv after updating to Big Sur.

__Solution__: Referenced from [this](https://github.com/pyenv/pyenv/issues/1739) Github issue.

Run the following command:

```
CFLAGS="-I$(brew --prefix openssl)/include -I$(brew --prefix bzip2)/include -I$(brew --prefix readline)/include -I$(xcrun --show-sdk-path)/usr/include" \
LDFLAGS="-L$(brew --prefix openssl)/lib -L$(brew --prefix readline)/lib -L$(brew --prefix zlib)/lib -L$(brew --prefix bzip2)/lib" \
pyenv install --patch 3.6.10 < <(curl -sSL https://github.com/python/cpython/commit/8ea6353.patch\?full_index\=1)
```