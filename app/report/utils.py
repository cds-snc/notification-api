from io import StringIO
from typing import Any

from sqlalchemy import func, text
from sqlalchemy.orm import aliased

from app import db
from app.aws.s3 import stream_to_s3
from app.models import Job, Notification, Template, User

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


def get_csv_file_data(serialized_notifications: list[Any], lang="en") -> bytes:
    """Builds a CSV file from the serialized notifications data and returns a binary string"""
    csv_file = StringIO()
    csv_file.write("\ufeff")  # Add BOM for UTF-8
    csv_file.write(",".join([_l(n) for n in CSV_FIELDNAMES]) + "\n")

    for notification in serialized_notifications:
        csv_file.write(serialized_notification_to_csv(notification, lang=lang))

    string = csv_file.getvalue()
    encoded_string = string.encode("utf-8")
    return encoded_string


def build_notifications_query(service_id, notification_type, days_limit=7):
    """
    Builds and returns an SQLAlchemy query for notifications with the specified parameters.

    Args:
        service_id: The ID of the service to query
        notification_type: The type of notifications to include
        days_limit: Number of days to look back in history

    Returns:
        SQLAlchemy query object for notifications
    """
    # Create aliases for the tables to make the query more readable
    n = aliased(Notification)
    t = aliased(Template)
    j = aliased(Job)
    u = aliased(User)

    # Build the query using SQLAlchemy
    return (
        db.session.query(
            n.to.label("Recipient"),
            t.name.label("Template"),
            n.notification_type.label("Type"),
            func.coalesce(u.name, "").label("Sent by"),
            func.coalesce(u.email_address, "").label("Sent by email"),
            func.coalesce(j.original_file_name, "").label("Job"),
            n.status.label("Status"),
            func.to_char(n.created_at, "YYYY-MM-DD HH24:MI:SS").label("Time"),
        )
        .join(t, t.id == n.template_id)
        .outerjoin(j, j.id == n.job_id)
        .outerjoin(u, u.id == n.created_by_id)
        .filter(
            n.service_id == service_id,
            n.notification_type == notification_type,
            n.created_at > func.now() - text(f"interval '{days_limit} days'"),
        )
        .order_by(n.created_at.desc())
    )


def compile_query_for_copy(query):
    """
    Compiles an SQLAlchemy query into a PostgreSQL COPY command string.

    Args:
        query: An SQLAlchemy query object

    Returns:
        String containing the compiled COPY command
    """
    compiled_query = query.statement.compile(dialect=db.engine.dialect, compile_kwargs={"literal_binds": True})
    return f"COPY ({compiled_query}) TO STDOUT WITH CSV HEADER"


def stream_query_to_s3(copy_command, s3_bucket, s3_key):
    """
    Executes a database COPY command and streams the results to S3.

    Args:
        copy_command: The PostgreSQL COPY command to execute
        s3_bucket: The S3 bucket name
        s3_key: The S3 object key
    """
    conn = db.engine.raw_connection()
    try:
        cursor = conn.cursor()
        stream_to_s3(
            bucket_name=s3_bucket,
            object_key=s3_key,
            copy_command=copy_command,
            cursor=cursor,
        )
    finally:
        conn.close()


def generate_csv_from_notifications(service_id, notification_type, days_limit=7, s3_bucket=None, s3_key=None):
    """
    Generate CSV using SQLAlchemy for improved compatibility and type safety, and stream it directly to S3.

    Args:
        service_id: The ID of the service to query
        notification_type: The type of notifications to include
        days_limit: Number of days to look back in history (default: 7)
        s3_bucket: The S3 bucket name to store the CSV (required)
        s3_key: The S3 object key for the CSV (required)
    """
    query = build_notifications_query(service_id, notification_type, days_limit)
    copy_command = compile_query_for_copy(query)
    stream_query_to_s3(copy_command, s3_bucket, s3_key)
