from io import StringIO
from typing import Any

CSV_FIELDNAMES = [
    "Recipient",
    "Template",
    "Type",
    "Sent by",
    "Sent by email",
    "Job",
    "Status",
    "Time",
]


def _l(x):
    """Mock translation function for now"""
    return x


def serialized_notification_to_csv(serialized_notification, lang="en"):
    values = [
        serialized_notification["recipient"],
        serialized_notification["template_name"],
        serialized_notification["template_type"] if lang == "en" else _l(serialized_notification["template_type"]),
        serialized_notification["created_by_name"] or "",
        serialized_notification["created_by_email_address"] or "",
        serialized_notification["job_name"] or "",
        serialized_notification["status"] if lang == "en" else _l(serialized_notification["status"]),
        serialized_notification["created_at"],
    ]
    return ",".join(values) + "\n"


def get_csv_file_data(serialized_notifications: list[Any], lang="en", with_headers=True) -> bytes:
    """Builds a CSV file from the serialized notifications data and returns a binary string"""
    csv_file = StringIO()
    if with_headers:
        # Write the CSV header
        csv_file.write("\ufeff")  # Add BOM for UTF-8
        csv_file.write(",".join([_l(n) for n in CSV_FIELDNAMES]) + "\n")

    for notification in serialized_notifications:
        csv_file.write(serialized_notification_to_csv(notification, lang=lang))

    string = csv_file.getvalue()
    encoded_string = string.encode("utf-8")
    return encoded_string
