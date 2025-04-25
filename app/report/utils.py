from flask import current_app
from sqlalchemy import case, func, text
from sqlalchemy.orm import aliased

from app import db
from app.aws.s3 import stream_to_s3
from app.config import QueueNames
from app.dao.templates_dao import dao_get_template_by_id
from app.models import EMAIL_STATUS_FORMATTED, KEY_TYPE_NORMAL, SMS_STATUS_FORMATTED, Job, Notification, Service, Template, User
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
    # notification types
    "email": "courriel",
    "sms": "sms",
    # notification statuses
    "Failed": "Échec",
    "Tech issue": "Problème technique",
    "Content or inbox issue": "Problème de contenu ou de boîte de réception",
    "Attachment has virus": "La pièce jointe contient un virus",
    "Delivered": "Livraison réussie",
    "In transit": "Envoi en cours",
    "Exceeds Protected A": "Niveau supérieur à Protégé A",
    "Carrier issue": "Problème du fournisseur",
    "No such number": "Numéro inexistant",
    "Sent": "Envoyé",
    "Blocked": "Message bloqué",
    "No such address": "Adresse inexistante",
    # "Can't send to this international number": "" # no translation exists for this yet
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


def build_notifications_query(service_id, notification_type, language, notification_statuses=[], days_limit=7):
    """
    Builds and returns an SQLAlchemy query for notifications with the specified parameters.

    Args:
        service_id: The ID of the service to query
        notification_type: The type of notifications to include
        language: "en" or "fr"
        days_limit: Number of days to look back in history
        notification_statuses: List of notification statuses to filter by
    Returns:
        SQLAlchemy query object for notifications
    """
    # Create aliases for the tables to make the query more readable
    n = aliased(Notification)
    t = aliased(Template)
    j = aliased(Job)
    u = aliased(User)

    # Build the inner subquery (returns enum values, cast as text for notification_type)
    query_filters = [
        n.service_id == service_id,
        n.notification_type == notification_type,
        n.created_at > func.now() - text(f"interval '{days_limit} days'"),
    ]

    if notification_statuses:
        query_filters.append(n.status.in_(notification_statuses))

    inner_query = (
        db.session.query(
            n.to.label("to"),
            t.name.label("template_name"),
            n.notification_type.cast(db.String).label("notification_type"),
            u.name.label("user_name"),
            u.email_address.label("user_email"),
            j.original_file_name.label("job_name"),
            n.status.label("status"),
            n.created_at.label("created_at"),
            n.feedback_subtype.label("feedback_subtype"),
            n.feedback_reason.label("feedback_reason"),
        )
        .join(t, t.id == n.template_id)
        .outerjoin(j, j.id == n.job_id)
        .outerjoin(u, u.id == n.created_by_id)
        .filter(*query_filters)
        .order_by(n.created_at.desc())
        .subquery()
    )

    # Map statuses for translation
    translate = Translate(language).translate
    # Provider-failure logic for email
    provider_failure_email = case(
        [(inner_query.c.feedback_subtype.in_(["suppressed", "on-account-suppression-list"]), "Blocked")], else_="No such address"
    )
    # Provider-failure logic for sms
    provider_failure_sms = case(
        [
            (
                inner_query.c.feedback_reason.in_(["NO_ORIGINATION_IDENTITIES_FOUND", "DESTINATION_COUNTRY_BLOCKED"]),
                "Can't send to this international number",
            )
        ],
        else_="No such number",
    )

    email_status_cases = [(inner_query.c.status == k, translate(v)) for k, v in EMAIL_STATUS_FORMATTED.items()]
    sms_status_cases = [(inner_query.c.status == k, translate(v)) for k, v in SMS_STATUS_FORMATTED.items()]
    # Add provider-failure logic
    if notification_type == "email":
        email_status_cases.append((inner_query.c.status == "provider-failure", translate(provider_failure_email)))
        status_expr = case(email_status_cases, else_=inner_query.c.status)
    elif notification_type == "sms":
        sms_status_cases.append((inner_query.c.status == "provider-failure", translate(provider_failure_sms)))
        status_expr = case(sms_status_cases, else_=inner_query.c.status)
    else:
        status_expr = inner_query.c.status
    if language == "fr":
        status_expr = func.coalesce(func.nullif(status_expr, ""), "").label(translate("Status"))
    else:
        status_expr = status_expr.label(translate("Status"))

    # Outer query: translate notification_type for display
    notification_type_translated = case(
        [
            (inner_query.c.notification_type == "email", translate("email")),
            (inner_query.c.notification_type == "sms", translate("sms")),
        ],
        else_=inner_query.c.notification_type,
    ).label(translate("Type"))

    return db.session.query(
        inner_query.c.to.label(translate("Recipient")),
        inner_query.c.template_name.label(translate("Template")),
        notification_type_translated,
        func.coalesce(inner_query.c.user_name, "").label(translate("Sent by")),
        func.coalesce(inner_query.c.user_email, "").label(translate("Sent by email")),
        func.coalesce(inner_query.c.job_name, "").label(translate("Job")),
        status_expr,
        # Explicitly cast created_at to UTC, then to America/Toronto
        func.to_char(
            func.timezone("America/Toronto", func.timezone("UTC", inner_query.c.created_at)), "YYYY-MM-DD HH24:MI:SS"
        ).label(translate("Sent Time")),
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


def generate_csv_from_notifications(
    service_id, notification_type, language, notification_statuses=[], days_limit=7, s3_bucket=None, s3_key=None
):
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
    query = build_notifications_query(
        service_id=service_id,
        notification_type=notification_type,
        language=language,
        notification_statuses=notification_statuses,
        days_limit=days_limit,
    )
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
            "report_name_en": report_name_en,
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
