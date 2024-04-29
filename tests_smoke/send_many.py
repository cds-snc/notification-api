import argparse
import time
from datetime import datetime

import requests
from dotenv import load_dotenv
from smoke.common import (  # type: ignore
    Config,
    Notification_type,
    job_line,
    pretty_print,
    rows_to_csv,
)

DEFAULT_JOB_SIZE = 50000


def send_bulk_job(notification_type: Notification_type, job_size: int):
    """Send a bulk job of notifications

    Args:
        notification_type (Notification_type): email or sms
        job_size (int): number of notifications to send
    """

    template_id = Config.EMAIL_TEMPLATE_ID if notification_type == Notification_type.EMAIL else Config.SMS_TEMPLATE_ID
    to = Config.EMAIL_TO if notification_type == Notification_type.EMAIL else Config.SMS_TO
    header = "email address" if notification_type == Notification_type.EMAIL else "phone number"

    response = requests.post(
        f"{Config.API_HOST_NAME}/v2/notifications/bulk",
        json={
            "name": f"Large send {datetime.utcnow().isoformat()}",
            "template_id": template_id,
            "csv": rows_to_csv([[header, "var"], *job_line(to, job_size)]),
        },
        headers={"Authorization": f"ApiKey-v1 {Config.API_KEY}"},
    )
    if response.status_code != 201:
        pretty_print(response.json())
        print("FAILED: post failed")
        exit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--notifications", default=1, type=int, help="total number of notifications")
    parser.add_argument("-j", "--job_size", default=DEFAULT_JOB_SIZE, type=int, help=f"size of bulk send jobs (default {DEFAULT_JOB_SIZE})")
    parser.add_argument("--sms", default=False, action='store_true', help="send sms instead of emails")

    args = parser.parse_args()
    load_dotenv()

    notification_type = Notification_type.SMS if args.sms else Notification_type.EMAIL
    for start_n in range(0, args.notifications, args.job_size):
        num_sending = min(args.notifications - start_n, args.job_size)
        print(f"Sending {start_n} - {start_n + num_sending - 1} of {args.notifications}")
        send_bulk_job(notification_type, num_sending)
        time.sleep(1)


if __name__ == "__main__":
    main()
