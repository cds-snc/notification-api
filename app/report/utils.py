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


def generate_csv_from_notifications(service_id, notification_type, days_limit=7, s3_bucket=None, s3_key=None):
    """
    Generate CSV using SQLAlchemy for improved compatibility and type safety, and stream it directly to S3.
    """
    # Create aliases for the tables to make the query more readable
    n = aliased(Notification)
    t = aliased(Template)
    j = aliased(Job)
    u = aliased(User)

    # Build the query using SQLAlchemy
    query = (
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

    # Use COPY TO with the SQLAlchemy query
    conn = db.engine.raw_connection()
    try:
        cursor = conn.cursor()
        # Compile the query to a string
        compiled_query = f"COPY ({query.statement.compile(dialect=db.engine.dialect, compile_kwargs={'literal_binds': True})}) TO STDOUT WITH CSV HEADER"

        # Stream the data directly to S3
        stream_to_s3(
            bucket_name=s3_bucket,
            object_key=s3_key,
            copy_command=compiled_query,
            cursor=cursor,
        )
    finally:
        conn.close()
