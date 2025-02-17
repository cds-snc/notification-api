#!/bin/bash

# Setup
current_month=$(date "+%Y.%m")
current_time=$(date "+%Y.%m.%d-%H.%M.%S")
perf_test_aws_s3_bucket="${PERF_TEST_AWS_S3_BUCKET:-notify-performance-test-results-staging}"
perf_test_csv_directory_path="${PERF_TEST_CSV_DIRECTORY_PATH:-/tmp/notify_performance_test}"
perf_test_results_folder="$perf_test_csv_directory_path/$current_month/$current_time"

mkdir -p "$perf_test_results_folder"

cd tests_nightly_performance || exit 1

# Test 1 - Hammer the api
locust --config locust.conf \
       --locustfile blast_api.py \
       --users 3000 \
       --html "$perf_test_results_folder/index.html" --csv "$perf_test_results_folder/api_test"

# Sleep 15 minutes to allow the system to stabilize
sleep 900

# Test 2 - Max out email send rate
# This configuration should send 10K emails / minute for 10 minutes for 100K emails total.
# We run this test on Tuesday through Friday (just after midnight UTC) only.

if [ "$(date +%u)" -ge 2 ] && [ "$(date +%u)" -le 5 ]; then
    locust --config locust.conf \
       --locustfile email_send_rate.py \
       --users 5 \
       --csv "$perf_test_results_folder/email_send_rate_test"
fi

# Sleep 30 minutes to allow the tests to finish and the system to stabilize
sleep 1800

# Test 3 - Max out sms send rate
# This configuration should send 4K sms / minute for 10 minutes for 40K sms total.
# We run this test on Tuesday through Friday (just after midnight UTC) only.

if [ "$(date +%u)" -ge 2 ] && [ "$(date +%u)" -le 5 ]; then
    locust --config locust.conf \
       --locustfile sms_send_rate.py \
       --users 2 \
       --csv "$perf_test_results_folder/sms_send_rate_test"
fi

# Copy data to s3
aws s3 cp "$perf_test_csv_directory_path/" "s3://$perf_test_aws_s3_bucket" --recursive || exit 1

# Cleanup
rm -rf "${perf_test_csv_directory_path:?}"
