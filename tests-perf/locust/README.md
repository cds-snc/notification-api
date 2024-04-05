# Stress tests manual

This manual is meant for the Locust stress tests located in the same folder than this README.

## Goals

The following goals are meant with the stress-tests:

* Monitor behavior of a production-like environment under similar stress.
* Preemptively discover technical issues by overloading our staging environment.
* Fix discovered issues in the production-like environment and propagate to production.

Our stress-tests can also act as load-tests that are ran against our build pipeline in a daily manner at minimum:

* Ensure our system can take the expected daily traffic of notifications that we receive.
* Align and certify our SLA/SLO/SLI agreements negotiated with our clients.
* Discover regressions related to performance that new changes can affect on our code base and infrastructure.

## How to configure the stress tests

There is an override system that [Locust implements with configuration parameters](https://docs.locust.io/en/stable/configuration.html). It can read values from the command-line, environment variables or custom configuration file. The order is, as defined by its own documnentation:

```doc
~/locust.conf -> ./locust.conf -> (file specified using --conf) -> env vars -> cmd args
```

Latest values read will override previous ones, hence command-line arguments will take precedence over everything.

The current directory has a `locust.conf` file where default configuration values are defined.

Note that the `host` value can also be defined within the `User` classes such as found in the `locust-notifications.py` file. This overriden value from its parent is the default values but will be overriden by the enumerated mechanism above.

You should not have to modify the configuration to run the stress-tests locally.

## How to run the stress tests

There are two ways to run Locust, with the UI or headless.

### Add the following to your .env file (see 1Password):

```
PERF_TEST_AUTH_HEADER =
PERF_TEST_BULK_EMAIL_TEMPLATE_ID=
PERF_TEST_EMAIL_WITH_LINK_TEMPLATE_ID=
PERF_TEST_EMAIL_TEMPLATE_ID=
PERF_TEST_EMAIL_WITH_ATTACHMENT_TEMPLATE_ID=
PERF_TEST_SMS_TEMPLATE_ID =
```

### With the UI

Locally, simply run:

```shell
locust -f .\locust-notifications.py
```

Follow the localhost address that the console will display to get to the UI. It will ask you how many total users and spawned users you want configured. Once setup, you can manually start the tests via the UI and follow the summary data and charts visually.

### Headless, via the command line

You can pass the necessary parameters to the command line to run in the headless mode. For example:

```shell
locust -f .\locust-notifications.py --headless --users=5500 --spawn-rate=200 --run-time=10m
```

You can also modify the *locust.config* file to enable the headless mode and define the necessary users, spawn rate and run time.

## Email send rate test

We also max out the email send rate by sending 2000 x 5 emails per minute for 10 minutes. This can be run manually with the command
```
locust --headless --host https://api.staging.notification.cdssandbox.xyz --locustfile tests-perf/locust/send_rate_email.py --users 5 --run-time 1m --spawn-rate 1
```

### Performance Testing on AWS

We run Notify performance tests on a daily manner through AWS ECS tasks
running on a Fargate cluster. It is automatically triggered by a
[CloudWatch event target](https://github.com/cds-snc/notification-terraform/blob/a5fcbf0d0e2ff5cd78952bf5c8f9f2dfd5d3c93c/aws/performance-test/cloudwatch.tf#L10).

It is possible to manually launch it though via the AWS console of the
ECS task. In order to do so, perform the following steps:

1. [Log into the AWS console](https://cds-snc.awsapps.com/start#/)
   for the staging environment.
2. [Head over to the Task Definitions](https://ca-central-1.console.aws.amazon.com/ecs/home?region=ca-central-1#/taskDefinitions)
   page within the ECS console.
3. Select the `performance_test_cluster` task definition.
4. Click on *Actions* button and select *Run*.
5. On the new page, let's fill the following details to get the task
   to run.
   1. Leave the default cluster strategy as-is.
   2. Select `Linux` as the operating system.
   3. Leave task definition, platform version as-is.
   4. Make sure the desired cluster is selected to run the task with.
   5. Number of task and task group can be left as-is, normally set to 1 task.
   6. For the VPC and security groups section, select the `notification-canada-ca` VPC.
   7. Then select all public subnets, 3 at the moment of this writing.
   8. Select the security group named `perf_test`.
   9. Other options can be left as-is: you should be all set and ready.
   10. Click the *Run Task* button!
6. Once the task is ran, you can select it from the list of running tasks.
    1. To see the logs of the running task and once you are in the task page, expand the container section. There should be a link to *View logs in CloudWatch* under the *Log Configuration* section.
7. On performance test completion, [the results should be in the `notify-performance-test-results-staging` S3 bucket](https://s3.console.aws.amazon.com/s3/buckets/notify-performance-test-results-staging?region=ca-central-1&tab=objects). Look into the folder that represents the proper timestamp for the test execution and open the `index.html` file located within.
8. The performance tests results should also be published [in this GitHub repository](https://github.com/cds-snc/notification-performance-test-results) every day at midnight. If you just executed the test, it will take some delay to have the tests published.