#!/bin/bash

current_time=$(date "+%Y.%m.%d-%H.%M.%S")
load_test_aws_s3_bucket=${LOAD_TEST_AWS_S3_BUCKET:-notify-perfortmance-test-results-staging}
load_test_csv_directory_path=${LOAD_TEST_CSV_DIRECTORY_PATH:-/tmp/notify_performance_test}

mkdir -p $load_test_csv_directory_path/$current_time

locust --headless --config tests-perf/locust/locust.conf --csv $load_test_csv_directory_path/$current_time/load_test

aws s3 cp $load_test_csv_directory_path/ "s3://$load_test_aws_s3_bucket" --recursive | grep -q 'An error occurred' && exit 1

rm -rf $load_test_csv_directory_path/$current_time
