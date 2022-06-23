# Running a Subset of Tests Using Containers

You can run specific test directories or files rather than the entire suite as follows.  These instructions assume that you have previously run the docker-compose command to start the local ecosystem and, therefore, that all migrations have been applied to the database and the default container network, ci_default, exists.

## Setting Environment Variables

The docker-compose command used to run the full test suite sets environment variables.  Step 3 below references the file env_vars for the same purpose.

## Setup

1. Stop all running containers associated with Notification-api.
2. Start the Postgres (ci_db_1) container, and any other containers required by the functionality under test: `docker start ci_db_1`.  All migrations should already be applied.
3. Start a test container shell by running `docker run --rm -it -v "<absolute path to notification-api>:/app" --env-file tests/env_vars ci_test bash`.
4. Add the test container started in the previous step to the default network: `docker network connect ci_default <test container name or ID>`.
5. Run `py.test -h` to see the syntax for running tests.  Without flags, you can run `py.test [file or directory]...`.

## Running Individual Tests

This is an example of running a specific test in a test file:

```$ py.test tests/lambda_functions/va_profile/test_va_profile_integration.py::test_va_profile_cache_exists```

## A Note About .bash_history

Running Bash commands on a container with read-write access, such as ci_test, will result in the creation of .bash_history in your notification_api/ directory.  That file is in .gitignore.
