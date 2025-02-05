# Notification API

This repository implements:

- the public-facing REST API for Notification built on the GOV.UK Notify platform, which teams can integrate with using [their clients](https://www.notifications.service.gov.uk/documentation)
- an internal-only REST API built using Flask to manage services, users, templates, etc (this is what the [admin app](http://github.com/cds-snc/notification-admin) talks to)
- asynchronous workers built using Celery to put things on queues and read them off to be processed, sent to providers, updated, etc
  
## API Documentation

VANotify OpenAPI specification can be downloaded [here](https://github.com/department-of-veterans-affairs/notification-api/blob/main/documents/openapi/openapi.yaml).

Postman collection and environment files are available [here](https://github.com/department-of-veterans-affairs/notification-api/tree/main/documents/postman).

Information about service callback setup is available [here](/app/callback/README.md).

## Functional Constraints

We currently do not:

- support sending of letters
- receive a response if text messages were delivered or not
- receive status updates from our email provider (Granicus) while waiting for ESECC process to be completed

---

## Table of Contents

- [Notification API](#notification-api)
  - [API Documentation](#api-documentation)
  - [Functional Constraints](#functional-constraints)
  - [Table of Contents](#table-of-contents)
  - [Local Development Using Docker](#local-development-using-docker)
    - [Run the local Docker containers](#run-the-local-docker-containers)
    - [Creating database migrations](#creating-database-migrations)
    - [Unit testing](#unit-testing)
    - [Pre-commit hooks](#pre-commit-hooks)
    - [Using Localstack](#using-localstack)
      - [Setup](#setup)
      - [Verification](#verification)
  - [Using Localstack ECR](#using-localstack-ecr)
  - [Local Development without docker](#local-development-without-docker)
    - [Prerequisite installation](#prerequisite-installation)
  - [Maintaining Docker Images](#maintaining-docker-images)
  - [Deployment Workflow](#deployment-workflow)
    - [Update Dependencies](#update-dependencies)
  - [Creating a PR](#creating-a-pr)
  - [Release Process](#release-process)
    - [Create a release for Perf](#create-a-release-for-perf)
    - [Create a release for Staging](#create-a-release-for-staging)
    - [Promote a release for Production](#promote-a-release-for-production)
  - [To Run the Queues](#to-run-the-queues)
  - [AWS Lambda Functions](#aws-lambda-functions)
  - [Running Code Scans](#running-code-scans)
  - [Using our Endpoints](#using-our-endpoints)
    - [Sending a notification](#sending-a-notification)
  - [Testing Template Changes](#testing-template-changes)
  - [Generic Internal Endpoints](#generic-internal-endpoints)
  - [Using Mountebank Stubs](#using-mountebank-stubs)
  - [Triggering Tasks](#triggering-tasks)
  - [Adding Environment Variables to Task Definition Files](#adding-environment-variables-to-task-definition-files)
  - [Frequent Problems](#frequent-problems)

---

## Local Development Using Docker

[Docker](https://www.docker.com/) is the prefered development environment.  Ensure you have Docker Engine installed or otherwise can run containers.

`.local.env` contains all necessary environmental variables and is read automatically in local development and github actions that do not deploy to AWS.


**Rebuild `notification_api` whenever Dockerfile or poetry.lock changes.**

The associated container will have your local notification-api/ directory mounted in read-write mode, and Flask will run in development mode.  Changes you make to the code should trigger Flask to restart on the container. The volume specified in `ci/docker-compose-local.yml` allows the container to read and write from your local file system. If you wish to isolate the built container from your filesystem, comment out the volume, but you will have to also comment out the `ENTRYPOINT` because `scripts/save_certificate.sh` saves data to the filesystem.  When working on the Docker container, this can be useful to verify the expected data is in the expected spot when deployed to a non-local environment.

### Run the local Docker containers

To run the app, and its ecosystem, locally, run:

```bash
docker compose -f ci/docker-compose-local.yml build app && docker compose -f ci/docker-compose-local.yml up
```
If you have previously built this it will be cached. Any changes to the the stages will result in continuation from that point.

If AWS SES is enabled as a provider, you may need to run the following command to give the (simulated) SES permission to (pretend to) send e-mails:

```bash
aws ses verify-email-identity --email-address stage-notifications@notifications.va.gov --endpoint-url=http://localhost:4566
```

To support running locally, the repository includes a default `app/version.py` file, which must be present at runtime to avoid raising an `ImportError`.  The deployed container build process overwrites this file with current values.

### Creating database migrations

Running `flask db migrate` on the container ci_app_1 errors because the files in the migrations folder are read-only.  Follow this procedure to create a database migration using Flask:

1. Ensure all containers are stopped and that the notification_api image has been built
2. Run migrations at least once e.g. `docker compose -f ci/docker-compose-local.yml up` and stop any running containers.
3. Run `docker compose -f ci/docker-compose-local-migrate.yml up`.  This creates the container ci_app_migrate with your local notification-api directory mounted in read-write mode.  The container runs `flask db migrate` and exits.
4. Press Ctrl-C to stop the containers, and identify the new file in `migrations/versions/`.

### Unit testing
See the [tests README.md](tests/README.md) for information.

### Pre-commit hooks

This repository uses [pre-commit](https://pre-commit.com/) and [talisman](https://github.com/thoughtworks/talisman) to scan changes for keys and secrets.  To set it up, install the required dependencies `pre-commit` and `go`.

OSX users can run `brew bundle` and then `pre-commit install` to register the git hooks.  The configuration is stored in .pre-commit-config.yaml.

Ruff has been added to the pre-commit hook in place of flake8. See [documentation](https://github.com/department-of-veterans-affairs/vanotify-team/blob/main/Engineering/formatter.md) for setup.


### Using Localstack

#### Setup
1. Sign up for [Localstack](https://app.localstack.cloud/sign-up).
 2. Go here and get your auth token - https://app.localstack.cloud/workspace/auth-token.  Put it in your environment,  .i.e.~/.zshrc or ~/.zsh_profile
3. Add a localstack profile to your ~/.aws/config. This will allow you to set an AWS_PROFILE environment variable in a shell, and the aws cli will use that profile. If you don't have a ~/.aws/config then maybe you don't have the cli, get it [here](https://aws.amazon.com/cli/).
```
[profile localstack]
region = us-east-1
endpoint_url = http://localhost:4566
output = json
```
4. Add localstack credentials to ~/.aws/credentials
```
[localstack]
aws_access_key_id = test
aws_secret_access_key = test
```
5. Start a localstack container, either through the [web interface](https://app.localstack.cloud/instances) or there is a native desktop app you can download. Make sure when starting the container you enter your localstack auth token, or the pro features will not be available.
6. Use this aws provider in Terraform
```
provider "aws" {
  profile                     = "localstack"
  s3_use_path_style           = false
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true

  endpoints {
    cloudwatch     = "http://localhost:4566"
    dynamodb       = "http://localhost:4566"
    iam            = "http://localhost:4566"
    lambda         = "http://localhost:4566"
    s3             = "http://s3.localhost.localstack.cloud:4566"
    secretsmanager = "http://localhost:4566"
    sns            = "http://localhost:4566"
    sqs            = "http://localhost:4566"
    ssm            = "http://localhost:4566"
  }
}
```

#### Verification

1. You should now be able to terraform resources in Localstack! Verify by creating a new directory and putting this file (`main.tf`) in it -
```
# main.tf
provider "aws" {
  profile                     = "localstack"
  s3_use_path_style           = false
  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true

  endpoints {
    cloudwatch     = "http://localhost:4566"
    dynamodb       = "http://localhost:4566"
    iam            = "http://localhost:4566"
    lambda         = "http://localhost:4566"
    s3             = "http://s3.localhost.localstack.cloud:4566"
    secretsmanager = "http://localhost:4566"
    sns            = "http://localhost:4566"
    sqs            = "http://localhost:4566"
    ssm            = "http://localhost:4566"
  }
}

resource "aws_s3_bucket" "test-bucket" {
  bucket = "test-bucket"
}
```
2. Initialize terraform and apply the plan:
``` sh
terraform init
```
``` sh
terraform apply
```
3. The localstack [web console](https://app.localstack.cloud/inst/default/resources/s3) should show the bucket and the aws cli should list it:
``` sh
aws s3 ls
2024-08-15 07:20:47 test-bucket
```

## Using Localstack ECR

The basic idea is to build a docker image, tag it, push it to ECR. This is useful for services which require an image in a repository (having it in your docker images is not enough). From the localstack [web console](https://app.localstack.cloud/inst/default/resources/ecr/repository/vanotify-local-api/images) you can view push commands for a repository, but here are the basics. If you create a repository like this:

``` terraform
resource "aws_ecr_repository" "api_ecr" {
  name = "test_api"
}
```

Then your build-tag-push docker commands would be

``` sh
docker build -t test_api .
```
``` sh
docker tag test_api:latest 000000000000.dkr.ecr.us-east-1.localhost.localstack.cloud:4566/test_api:latest
```
``` sh
docker push 000000000000.dkr.ecr.us-east-1.localhost.localstack.cloud:4566/test_api:latest
```
The image should be useable, .e.g.:
``` sh
docker run --rm --env-file=.local.env 000000000000.dkr.ecr.us-east-1.localhost.localstack.cloud:4566/test_api
```

## Local Development without docker
This is not maintained. The recommendation is that individuals use Docker, but we have left this here for those that may wish to try it.

### Prerequisite installation

 On OS X:

 1. Install PyEnv with Homebrew. This will preserve your sanity.

  `brew install pyenv`

 2. Install Python 3.10 (or whatever version is specified in `pyproject.toml`)
 Then follow from instructions for rest of pyenv setup, [see step 3 here](https://github.com/pyenv/pyenv#basic-github-checkout)

 Note: For MacOS devs who are using Big Sur, Monterey, standard pyenv python installation will be failed in most case. I found [this solution](https://github.com/pyenv/pyenv/issues/2143#issuecomment-1070640288) so only 3.7.13, 3.8.13, 3.9.11 and 3.10.3 works fine.

 `pyenv install 3.10.13`

 3. If you expect no conflicts, set `3.10.13` as your default

 `pyenv global 3.10.13`

Upgrade the versions of `pip` and `virtualenvwrapper`

 ```bash
 pip install --upgrade pip
 pip install --upgrade virtualenvwrapper
 ```

- to check Python version currently being used, run `pyenv version`

- to check list of Python versions installed, run `pyenv versions`

 4. Ensure it installed by running

 `python --version`

 if it did not, take a look here: <https://github.com/pyenv/pyenv/issues/660>

 5. Install `virtualenv`:

 `pip install virtualenvwrapper`

 Note:

- if you update to a later Python version, you will need to repeat steps 5~7 with reference to the new version.

 6. Add the following to your shell rc file. ex: `.bashrc` or `.zshrc`

 ```bash
 export WORKON_HOME=$HOME/.virtualenvs
 export PROJECT_HOME=$HOME/Devel
 source  ~/.pyenv/versions/3.10.13/bin/virtualenvwrapper.sh
 ```

 7. Restart your terminal and make your virtual environtment:

 `mkvirtualenv -p ~/.pyenv/versions/3.10.13/bin/python notification-api`

 8. You can now return to your environment any time by entering

 `workon notification-api`

  Exit the virtual environment by running `deactivate`

 9. Install [Postgres.app](http://postgresapp.com/).

  > Note:
     >
     > - check version of Postgres used in `ci/docker-compose.yml` to install correct `db:image` version.
     > - If you do not have PostgresSQL installed, run `brew install postgresql`
     >
 10. Create the database for the application

 `createdb --user=postgres notification_api`

 11. Install all dependencies

 `poetry install`

 12. Generate the version file ?!?

 `make generate-version-file`

 13. Run all DB migrations

 `flask db upgrade`

 Note:

- For list of flask migration cli commands, see `/migrations/README.md`

 14. Run the service

 `flask run -p 6011 --host=0.0.0.0`

## Maintaining Docker Images

This application defines Docker images for production, testing, and development via Dockerfile and YAML files in the "ci" directory.  These images depend on base images from [Docker Hub](https://hub.docker.com/), and the base images provide specific versions of various technologies.  These images dependencies should be updated periodically to continue using actively supported versions.

| Technology | End of Support | Notes | Affected Files in ci/ |
|------------|----------------|-------|-----------------------|
| Python 3.10 | 04 October 2026 | | Dockerfile, Dockerfile.local |
| Alpine Linux 3.19 | 01 November 2025 | | Dockerfile, Dockerfile.local |
| Postgres 15 | [11 November 2027](https://www.postgresql.org/support/versioning/) | | docker-compose.yml, docker-compose-local.yml, docker-compose-local-migrate.yml, docker-compose-test.yml |
| localstack | None given.  The YAML files specifies v0.12.3.  As of March 2022, v0.14.1 is available. | As of March 2022, localstack requires Python 3.6-3.9. | docker-compose-local.yml |
| bbyars/mountebank 2.4.0 | None given. | Newer versions are available. | docker-compose-local.yml |
| redis | | No version specified. | docker-compose-local.yml |

To update the images, change the `FROM` directive at the top of Dockerfiles and the `image` directive in YAML files.  Rebuild affected dependent containers, and run the [unit tests](#unit-testing) to verify the changes.  For example, if ci/Dockerfile begins with the line "FROM python:3.10-alpine3.19", you could change it to "FROM python:3.12-alpine3.22".  Visit Docker Hub to see what version tags are available for a given image.

---

## Deployment Workflow

### Update Dependencies

Updating dependencies for the `notification_api` is done by ensuring [Poetry](https://python-poetry.org/) is installed, then running a simple command while within the root of `notification_api`. The `pyroject.toml` file contains all top-level dependencies, and Poetry manages everything else. The full process to upgrade is as follows:

1. From the root directory, and with Poetry 1.8 installed, run `poetry update`
2. Run all unit tests with `docker compose -f ci/docker-compose-test.yml up`
4. Deploy the code and ensure all regressions pass

## Creating a PR

When a ticket has been worked and is ready to be reviewed and merged in, we will create a new pull request (PR).

To open a PR:

- Make sure your branch is pushed up to the main repository

- The title of the PR should be formated to contain the ticket number of the issue being worked with a title

- The body should be filled out per the template that is provided

- Add in the correct tags that represent the PR

```markdown
Title: #443 Issue Title


# Description

Please include a summary of the change and which issue is fixed. Please also include relevant motivation and context. List any dependencies that are required for this change.

Fixes #443

## Type of change

Please delete options that are not relevant.

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] This change requires a documentation update

## How Has This Been Tested?

Please describe the tests that you ran to verify your changes. Provide instructions so we can reproduce. Please also list any relevant details for your test configuration

- [ ] Test A
- [ ] Test B

## Checklist

- [ ] My code follows the style guidelines of this project
- [ ] I have performed a self-review of my own code
- [ ] I have commented my code, particularly in hard-to-understand areas
- [ ] I have made corresponding changes to the documentation
- [ ] My changes generate no new warnings
- [ ] I have added tests that prove my fix is effective or that my feature works
- [ ] New and existing unit tests pass locally with my changes
- [ ] Any dependent changes have been merged and published in downstream modules
```

For tags, please make sure to add in additional tags to the PR based on the following categories:

```yaml
  categories:
    - title: Breaking Changes 🛠
      labels:
        - breaking-change
    - title: Exciting New Features 🎉
      labels:
        - enhancement
    - title: Bug Fixes 🐜
      labels:
        - bug
        - hotfix
    - title: Security Fixes 🔐
      labels:
        - cve
        - security
```

If the PR requires additional manual validation/testing then make sure to add in the `test` tag to the PR as well.

If the PR does not fit into these categories, then don't add a tag.

## Release Process

The API releases are managed by tags in the GitHub repo.

### Create a release for Perf

To create a new release, the user will create a new version tag in the git repository. This can be for the current `HEAD` or for a specific commit from a PR. The tag format will be `v(Major).(Minor).(Hotfix)` format. The Portal uses a similar method, so for version one of the Portal we created `v1.0.0` and with a single hotfix a new tag was created for `v1.0.1`.

Example commands for tagging:

```cli
git tag v2.0.0
git push origin v2.0.0
```

When a new tag is created with a `v` prefix and pushed to the repository, the tagging action will start. This action will checkout the tag, create testing notes based on PR's with the `test` tag applied to them, and then build and deploy to our performance (perf) environment, and run the regression.

### Create a release for Staging

After a tag has been deployed and the code is validated in perf, we create a `pre-release` for our staging environment.

- Login to GitHub and go to the notification-api repo. On the right side click on `Releases`

- Click on `Draft a new release`

- Select the tag to release from the `Choose a tag` dropdown

- Click on `Generate release notes` to generate the title and release notes for this release

- **Important**: Check the box `This is a pre-release`

- Click `Publish release` in order to push this pre-release

When a pre-release is created, the release action will trigger and this will pull the code from that tag, build a container, and deploy this to the staging environment. The pre-release will now be listed with the `pre-release` tag on the Releases page.

### Promote a release for Production

When a tag is ready to be moved to prodution, complete the following steps.

- Login to GitHub and go to the notification-api repo. On the right side click on `Releases`

- Select the pre-release tag to be updated and click on the penciel ✏️ icon in the upper right of the pre-release to edit

- Scroll to the bottom of the pre-release and find the checkbox for `This is a pre-release`

- Uncheck the box

- Click `Publish release` to push the release to production

When a release is generated it will trigger the release action which will checkout that tag, build and push the code to prodcution and deploy the new container.

---

## To Run the Queues

VA Notify uses [Celery](https://docs.celeryq.dev/en/stable/) to run batches of processes.

- `scripts/run_celery.sh`
- `scripts/run_celery_beat.sh`

---

## AWS Lambda Functions

This repository contains lambda function code in the lambda_functions/ directory.  The AWS infrastructure resources are part of the [vanotify-infra](https://github.com/department-of-veterans-affairs/vanotify-infra) repository.  For information about creating lambda functions, refer to the [AWS documentation](https://docs.aws.amazon.com/lambda/index.html).

When creating a new lambda function, define an associated job in the Github workflow [Build Lambda Functions](.github/workflows/lambda-functions.yaml) using the naming convention `deploy-{functon name}-lambda`.

---

## Running Code Scans

The instructions below are for running locally.  The scans also are implemented as jobs in continuous integration pipeline.

[Bandit](https://pypi.org/project/bandit/) scans for common security issues in Python code.

```bash
make check-vulnerabiltiies
```

[Safety](https://pyup.io/safety/) checks python dependencies for known security vulnerabilities.

```bash
make check-dependencies
```

---

## Using our Endpoints

If you are trying to hit our endpoints while running the app locally, make sure you are using `http` and not `https.`
For all other environments, use `https` instead of `http`. If you get some sort of seemingly random error, double check
those first!

You will need to set several environment variables in order to get the endpoints to work properly. They are as
follows:

- notification-api-url (either `127.0.0.1:6011` for local or our endpoints for everything else)
- notification-client-secret (the values for dev through prod should be in param store or 1Password)
- notification-admin-id: should be notify-admin for all environments
- api-key-id: not needed for local, should be in param store or 1Password for other environments

### Sending a notification

Instructions are for internal vanotify developer use. Clients will not have access to most of the mentioned endpoints.

A lot of our endpoints in Postman have some scripting that saves ids to environment variables, so you might see some
of these variables populated after you make requests.

- Grab a service id by using the Get Services endpoint. This variable should be saved as service-id in env vars.
  VANotify is a good one to use.
- Find a template that you want to use on the service using the Get Templates for Service endpoint. Make sure it's
  same type as the notification you want to send (e.g., email, sms)
- Create or get a user id by making requests to Create User or Get Users. Make sure the user you get/create has
  permissions to send notifications. The id should be saved as user-id in env vars
- Create a service api key using the Create API Key endpoint. This variable should be saved as service-api-key in env
  vars
- Make a request with the various Send SMS/Email endpoints depending on your recipient. Once sent, the notification-id
  will be saved as an env var.
- To get updates on what's happening with the notification, you can make a request to the Notification Status endpoint
  and see what the notification_status currently is

---

## Testing Template Changes

Jinja templates are pulled in from the [notification-utils](https://github.com/department-of-veterans-affairs/notification-utils) repo.  Jinja templates used in this repo: `email_template.jinja2`. To test jinja changes locally without needing to push changes to notification-utils, follow this procedure:

1. Make markup changes to `email_template.jinja2` (notifications_utils/jinja_templates/email_template.jinja2)

2. (optional) Modify notifications_utils/version.py and add -SNAPSHOT to version number, e.g. `'version.number-SNAPSHOT'`.  This will allow to easily revert local copy of notifications-utils in sites-packages to official version from git.

3. From within the notification-api virtual environment reinstall the utils dependency into the api repo, run:

    ```commandline
    pip install file:///path/to/notification-utils
    ```

4. See the changes locally!
    - Be sure the local server for notification-api is running to send an email.
    - Refer to section [Installation for Local Development](###local-installation-instruction) for local setup or [Running in Docker](###running-the-local-docker-containers) for Docker command to local startup.

5. Repeat steps 1, 2 and 3 until satisfied.

6. When finished run:

    ```commandline
    pip install -r requirements.txt
    ```

---

## Generic Internal Endpoints

There is an internal Flask route `/internal/<generic>` which can be used to mock external endpoints for integration testing.
`GET` requests return a text response in the form `"GET request received for endpoint {request.full_path}"` where
`request.full_path` is the url + query string. `POST` requests return a JSON response in the form `{<generic>: <request.json>}`. Both methods return a 200 and log the following attributes:

- headers
- method
- root_path
- path
- query_string
- json
- url_rule
- trace_id

In Datadog, the logs will appear as INFO level logs in the form - `Generic Internal Request <attribute>: <request.attribute>`

Example:

``` http
POST /internal/test1 HTTP/1.1
Accept: application/json, */*;q=0.5
Accept-Encoding: gzip, deflate
Connection: keep-alive
Content-Length: 14
Content-Type: application/json
Host: localhost:6011
User-Agent: HTTPie/3.2.2

{
    "foo": "bar"
}


HTTP/1.1 200 OK
Connection: close
Content-Length: 49
Content-Type: application/json
Date: Wed, 24 Jul 2024 18:30:19 GMT
Server: Werkzeug/3.0.3 Python/3.10.14
X-B3-SpanId: None
X-B3-TraceId: None

{
    "test1": {
        "foo": "bar"
    }
}
```


## Using Mountebank Stubs

We have some stubs set up for making requests to MPI and VA Profile located in `scripts/mountebank/stubs`. In order to
hit these, start up the app locally with Docker and make sure the mountebank container is running properly.

To hit the MPI endpoints, make a POST request to send a notification with the following information instead of the
email/phone number in the payload:

```json
"recipient_identifier": {
        "id_type": "PID",
        "id_value": <id value in stub url>
},
```

The ID value in the stub url is the number after `Patient/` and before the % sign (e.g., `400400` for
`/psim_webservice/fhir/Patient/400400%5EPI%5E200CORP%5EUSVBA$`).

For the VA Profile endpoints, make the same POST request to send a notification but use the following information
instead of an email/phone number in the payload:

```json
"recipient_identifier": {
        "id_type": "VAPROFILEID",
        "id_value": <id value in stub url>
},
```

The ID value in the stub url is the number after `v1/` (e.g., `2003` for `/cuf/contact-information/v1/2003/emails$`).

---

For the VA Profile communication item endpoint, you will need to remove the port (`:443`) from the URL before you
make the request while running locally.

## Triggering Tasks

We have provided a script for executing a celery task located at `scripts/trigger_task.py`. In order to execute these,
you will first need to log into AWS using the CLI, and ensure that you have the developer role. You can then execute
the script for the command line given that you provide the task name, prefix and routing key for the queue, and any
required arguments to the task. For example, running the command

```bash
python scripts/trigger_task.py --task-name generate-daily-notification-status-report --queue-prefix dev-notification- --routing-key delivery-status-result-tasks --task-args 2022-01-28
```

Will run the `generate-daily-notification-status-report` task in the queue `dev-notification-delivery-status-result-tasks` with
a date string of `2022-01-28` passed to the task.

## Adding Environment Variables to Task Definition Files

When adding environment variables to any `<filename>-task-definition.json` file, make sure you add them to the corresponding
`celery`and `celery-beat` files as well. We want to try and keep these consistent with each other.

---

## Frequent Problems

**Problem**: `assert 'test_notification_api' in db.engine.url.database, 'dont run tests against main db`

**Solution**: Do not specify a database in your `.env` file.

---

**Problem**: Messages are in the queue but not sending.

**Solution**: Check that `celery` is running.

---

**Problem**: `./Modules/posixmodule.c:10432:5: warning: code will never be executed [-Wunreachable-code]
Py_FatalError("abort() called from Python code didn't abort!");`

This error may occur while attempting to install pyenv after updating to Big Sur.

**Solution**: As referenced from [this](https://github.com/pyenv/pyenv/issues/1739) Github issue, run the following commands:

```bash
CFLAGS="-I$(brew --prefix openssl)/include -I$(brew --prefix bzip2)/include -I$(brew --prefix readline)/include -I$(xcrun --show-sdk-path)/usr/include" \
LDFLAGS="-L$(brew --prefix openssl)/lib -L$(brew --prefix readline)/lib -L$(brew --prefix zlib)/lib -L$(brew --prefix bzip2)/lib" \
pyenv install --patch 3.10.13 < <(curl -sSL https://github.com/python/cpython/commit/8ea6353.patch\?full_index\=1)
```

---

**Problem**: Unit tests pass locally but fail when run in Github as a pull request check

**Solution**: Ensure you have properly set environment variables.  When running unit tests locally with containers, the environmnet includes the variables declared in [docker-compose-test.yml](https://github.com/department-of-veterans-affairs/notification-api/blob/main/ci/docker-compose-test.yml).  However, Github does not use this YAML file.

Set environment variables for the Github Actions job runner in [tests.yaml](https://github.com/department-of-veterans-affairs/notification-api/blob/main/.github/workflows/tests.yaml).  You probably will want to define them in the `env` section of the `Run Tests` step of the `Test` job, but variables set anywhere are visible to subsequent steps within the same job.
