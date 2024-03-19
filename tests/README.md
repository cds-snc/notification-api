# Running a Subset of Tests Using Containers

You can run specific test directories, files, or individual tests rather than the entire suite as follows.  These instructions assume that you have previously run the docker-compose command to start the local ecosystem and, therefore, that all migrations have been applied to the database and the default container network, ci_default, exists.

## Setting Environment Variables

The docker-compose command used to run the full test suite sets environment variables.  Step 3 below references the file env_vars for the same purpose.

## Setup
There are two options for running ad hoc tests.
### Option 1
1. Stop all running containers associated with Notification-api.
2. Start the Postgres (ci_db_1) container, and any other containers required by the functionality under test: `docker start ci-db-1`.  All migrations should already be applied.
3. Start a test container shell by running `docker run --rm -it -v "$(pwd):/app" --env-file tests/env_vars --name ci-test --network ci_default ci-test bash`.
4. In the test container shell, run `pytest -h` to see the syntax for running tests.  Without flags, you can run `pytest [file or directory]...`.

### Option 2
1. Stop all running containers
2. Edit `scripts/run_tests.sh` by commenting any `pytest` execution and adding `tail -f` to the end of the file
3. Run `docker compose -f ci/docker-compose-test.yml up`
4. In a separate window run `docker exec -it ci-test-1 bash`
5. Execute any command, such as `pytest --durations 10 tests/app/celery`

## Running Individual Tests

This is an example of running a specific test in a test file from *within a test container shell*:

```
$ pytest tests/lambda_functions/va_profile/test_va_profile_integration.py::test_va_profile_cache_exists
```

## A Note About .bash_history

Running Bash commands on a container with read-write access, such as ci_test, will result in the creation of .bash_history in your notification_api/ directory.  That file is in .gitignore.

## Additional Options

Build and test the "ci_test" Docker image by running this command:

```bash
docker compose -f ci/docker-compose-test.yml up
```

**Rebuild ci_test whenever Dockerfile or poetry.lock changes.**

For a more interactive testing experience, edit `scripts/run_tests.sh` so that it does not execute any pytest command, and place `tail -f` on the final line e.g.
```bash
params="-rfe --disable-pytest-warnings --cov=app --cov-report=term-missing --junitxml=test_results.xml -q"
# pytest ${params} -n auto -m "not serial" tests/ && pytest ${params} -m "serial" tests/
display_result $? 2 "Unit tests"
tail -f

```

In a separate window execute:
```bash
docker exec -it ci-test-1 bash
```

This will allow exec into the `ci-test-1` container, from which any desired bash commands may be executed. If you wish to also have visibility into the database, simply execute the following in a new window:
```bash
docker exec -it ci-db-1 bash
```

Then login to the test database with:
```bash
psql -U postgres -d notification_api
```

You can then execute [psql](https://www.postgresql.org/docs/current/app-psql.html) commands.

The Github workflow also runs these tests when you push code.  Instructions for running a subset of tests are located in tests/README.md.
