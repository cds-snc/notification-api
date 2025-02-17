# Nightly performance tests

## Goals

These tests are run to help us:

- Monitor behavior of a production-like environment under similar stress.
- Preemptively discover technical issues by overloading our staging environment.
- Fix discovered issues in the production-like environment and propagate to production.

Our stress-tests can also act as load-tests that are ran against our build pipeline in a daily manner at minimum:

- Ensure our system can take the expected daily traffic of notifications that we receive.
- Align and certify our SLA/SLO/SLI agreements negotiated with our clients.
- Discover regressions related to performance that new changes can affect on our code base and infrastructure.

## Overview

We are running three performance tests:
- hammer the api (3000 POSTs / minute for 10 minutes, both singles and two row bulk jobs)
- max out the email send rate (100K emails POSTed over 10 minutes)
- max out the sms send rate (40K sms POSTed over 10 minutes)
  
The api test is run every night in [ECS](https://ca-central-1.console.aws.amazon.com/ecs/v2/clusters/performance_test_cluster/services?region=ca-central-1) while the send rate tests are run Tuesday through Friday (to save a bit of money)

These test are run by locust. The locust results (essentially whether there were POSTs that failed) are uploaded to [s3](https://s3.console.aws.amazon.com/s3/buckets/notify-performance-test-results-staging?region=ca-central-1&tab=objects) and [GitHub](https://github.com/cds-snc/notification-performance-test-results) and posted to Slack.

The [code to upload the results to GitHub and post to Slack](https://github.com/cds-snc/notification-performance-test-results/blob/main/.github/workflows/sync-performance-test-results.yml) is located in the [notification-performance-test-results](https://github.com/cds-snc/notification-performance-test-results) repository.

## Configuration

Some test configuration is in the `locust.conf` file. We also require a Notify api key and template ids
```
PERF_TEST_API_KEY=
PERF_TEST_EMAIL_TEMPLATE_ID_ONE_VAR=
PERF_TEST_SMS_TEMPLATE_ID_ONE_VAR=
```

## Running the tests manually

The tests are run automatically in ECS every night. To run manually in ECS refer to the [Tricks and Tips](https://docs.google.com/document/d/16LLelZ7WEKrnbocrl0Az74JqkCv5DBZ9QILRBUFJQt8/edit?tab=t.0#heading=h.72a482juoxa7) document. To run locally, create a local `.env` file and run a modified version of the locust lines in the fule `execute_and_publish_performance_test.sh`, for example to run with the locust gui you can use the `--headful` command.
```
locust --config locust.conf \
       --locustfile email_send_rate.py \
       --users 5 --headful
```
