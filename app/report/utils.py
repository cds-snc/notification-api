from sqlalchemy import func, text
from sqlalchemy.orm import aliased

from app import db
from app.aws.s3 import stream_to_s3
from app.models import Job, Notification, Template, User

FR_TRANSLATIONS = {
    "Recipient": "Destinataire",
    "Template": "Gabarit",
    "Type": "Type",
    "Sent by": "Envoyé par",
    "Sent by email": "Envoyé par courriel",
    "Job": "Tâche",
    "Status": "État",
    "Sent Time": "Heure d’envoi",
}


class Translate:
    def __init__(self, language="en"):
        """Initialize the Translate class with a language."""
        self.language = language
        self.translations = {
            "fr": FR_TRANSLATIONS,
        }

    def _(self, x):
        """Translate the given string based on the set language."""
        if self.language == "fr" and x in self.translations["fr"]:
            return self.translations["fr"][x]
        return x


def build_notifications_query(service_id, notification_type, language, days_limit=7):
    """
    Builds and returns an SQLAlchemy query for notifications with the specified parameters.

    Args:
        service_id: The ID of the service to query
        notification_type: The type of notifications to include
        language: "en" or "fr"
        days_limit: Number of days to look back in history

    Returns:
        SQLAlchemy query object for notifications
    """
    # Create aliases for the tables to make the query more readable
    n = aliased(Notification)
    t = aliased(Template)
    j = aliased(Job)
    u = aliased(User)

    _ = Translate(language)._

    # Build the query using SQLAlchemy
    return (
        db.session.query(
            n.to.label(_("Recipient")),
            t.name.label(_("Template")),
            n.notification_type.label(_("Type")),
            func.coalesce(u.name, "").label(_("Sent by")),
            func.coalesce(u.email_address, "").label(_("Sent by email")),
            func.coalesce(j.original_file_name, "").label(_("Job")),
            n.status.label(_("Status")),
            func.to_char(n.created_at, "YYYY-MM-DD HH24:MI:SS").label(_("Sent Time")),
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


def generate_csv_from_notifications(service_id, notification_type, language, days_limit=7, s3_bucket=None, s3_key=None):
    """
    Generate CSV using SQLAlchemy for improved compatibility and type safety, and stream it directly to S3.

    Args:
        service_id: The ID of the service to query
        notification_type: The type of notifications to include
        language: "en" or "fr"
        days_limit: Number of days to look back in history (default: 7)
        s3_bucket: The S3 bucket name to store the CSV (required)
        s3_key: The S3 object key for the CSV (required)
    """
    query = build_notifications_query(service_id, notification_type, language, days_limit)
    copy_command = compile_query_for_copy(query)
    stream_query_to_s3(copy_command, s3_bucket, s3_key)
