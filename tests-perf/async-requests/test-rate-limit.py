import grequests
from dotenv import dotenv_values
import os 

Config = dotenv_values(".env")  # config = {"USER": "foo", "EMAIL": "foo@example.org"}
no_bounce = "success@simulator.amazonses.com"
bounce = "bounce@simulator.amazonses.com"
ooto = "ooto@simulator.amazonses.com"
sms_success = "14254147755"
sms_failure = "14254147167"

data = {
    "name": "send 1",
    "rows": [
        ["email address"],
        [no_bounce],
    ],
    "template_id": os.getenv("PERF_TEST_BULK_EMAIL_TEMPLATE_ID"),
}

rs = (grequests.post(f"{Config['API_HOST_NAME_STAGING']}/v2/notifications/bulk", json=data, headers={"Authorization": f"ApiKey-v1 {Config['API_KEY_STAGING']}"}) for _ in range(int(Config['NUMBER_OF_REQUESTS'])))

def exception_handler(request, exception):
    print("Request failed")
    print("request", request)
    print("exception", exception)

responses = grequests.map(rs, exception_handler=exception_handler, stream=False)

with open("responses.txt", "w") as f:
    for response in responses:
        f.write(f"status_code: {response.status_code}\n")
        f.write(str(response.json()) + "\n")
        f.write("\n")