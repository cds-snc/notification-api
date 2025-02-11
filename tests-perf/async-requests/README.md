# Test the API rate-limit using Async Requests

Steps:
1. Build the dev container
2. `cd tests-perf/async-requests`
3. create a local .env file in this folder with the following values:
```
API_KEY_STAGING=***your key***
API_HOST_NAME_STAGING=https://api.staging.notification.cdssandbox.xyz
NUMBER_OF_REQUESTS=2 # I used 2000 but be careful
```
4. run with `> python scripts/test-rate-limit/test_rate_limit.py`
5. inspect the contents of responses.txt - if you exceed the rate limit you will see status_code: 429