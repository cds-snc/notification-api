from flask import current_app
from sqlalchemy import func, text
from sqlalchemy.orm import aliased

from app import db
from app.aws.s3 import stream_to_s3
from app.config import QueueNames
from app.dao.templates_dao import dao_get_template_by_id
from app.models import KEY_TYPE_NORMAL, Job, Notification, Service, Template, User
from app.notifications.process_notifications import persist_notification, send_notification_to_queue

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

    def translate(self, x):
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

    translate = Translate(language).translate

    # Build the query using SQLAlchemy
    return (
        db.session.query(
            n.to.label(translate("Recipient")),
            t.name.label(translate("Template")),
            n.notification_type.label(translate("Type")),
            func.coalesce(u.name, "").label(translate("Sent by")),
            func.coalesce(u.email_address, "").label(translate("Sent by email")),
            func.coalesce(j.original_file_name, "").label(translate("Job")),
            n.status.label(translate("Status")),
            func.to_char(n.created_at, "YYYY-MM-DD HH24:MI:SS").label(translate("Sent Time")),
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


def send_requested_report_ready(report) -> None:
    """
    We are sending a notification to the user to inform them that their requested
    report is ready.
    """
    template = dao_get_template_by_id(current_app.config["REPORT_DOWNLOAD_TEMPLATE_ID"])
    service = Service.query.get(current_app.config["NOTIFY_SERVICE_ID"])
    report_service = Service.query.get(report.service_id)

    if template.template_type == "email":
        report_name_en = f"{report.requested_at.date()}-emails-{report_service.name}"
        report_name_fr = f"{report.requested_at.date()}-courriels-{report_service.name}"
    else:
        report_name_en = f"{report.requested_at.date()}-sms-{report_service.name}"
        report_name_fr = f"{report.requested_at.date()}-sms-{report_service.name}"

    saved_notification = persist_notification(
        template_id=template.id,
        template_version=template.version,
        recipient=report.requesting_user.email_address,
        service=service,
        personalisation={
            "name": report.requesting_user.name,
            "report_name": report_name_en,
            "report_name_fr": report_name_fr,
            "service_name": report_service.name,
            "hyperlink_to_page_en": f"{current_app.config['ADMIN_BASE_URL']}/services/{report_service.id}/reports",
            "hyperlink_to_page_fr": f"{current_app.config['ADMIN_BASE_URL']}/services/{report_service.id}/reports?lang=fr",
        },
        notification_type=template.template_type,
        api_key_id=None,
        key_type=KEY_TYPE_NORMAL,
        reply_to_text=service.get_default_reply_to_email_address(),
    )

    send_notification_to_queue(saved_notification, False, queue=QueueNames.NOTIFY)
