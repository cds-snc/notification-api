#!/bin/bash

# For now let's not do the old perf test, just the email send rate test

# Setup
# current_time=$(date "+%Y.%m.%d-%H.%M.%S")
# perf_test_aws_s3_bucket=${PERF_TEST_AWS_S3_BUCKET:-notify-performance-test-results-staging}
# perf_test_csv_directory_path=${PERF_TEST_CSV_DIRECTORY_PATH:-/tmp/notify_performance_test}
# mkdir -p $perf_test_csv_directory_path/$current_time

# # Run old performance test and copy results to S3
# locust --headless --config tests-perf/locust/locust.conf --html $perf_test_csv_directory_path/$current_time/index.html --csv $perf_test_csv_directory_path/$current_time/perf_test
# aws s3 cp $perf_test_csv_directory_path/ "s3://$perf_test_aws_s3_bucket" --recursive || exit 1

# # Sleep 15 minutes to allow the system to stabilize
# sleep 900

# Run email send rate performance test
# This configuration should send 10K emails / minute for 10 minutes for 100K emails total.
# We run this test on Tuesday through Friday (just after midnight UTC) only.
if [ "$(date +%u)" -ge 2 ] && [ "$(date +%u)" -le 5 ]; then
    locust --headless --host https://api.staging.notification.cdssandbox.xyz --locustfile tests-perf/locust/send_rate_email.py --users 5 --run-time 10m --spawn-rate 1
fi

# Cleanup
rm -rf $perf_test_csv_directory_path/$current_time
