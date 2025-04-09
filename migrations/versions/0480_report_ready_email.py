"""Add report download template

Revision ID: 0480_report_ready_email
Revises: 0479_update_reports_url
Create Date: 2025-04-09 12:00:00.000000

"""

from datetime import datetime

from alembic import op
from flask import current_app

revision = "0480_report_ready_email"
down_revision = "0479_update_reports_url"

report_download_template_id = current_app.config.get("REPORT_DOWNLOAD_TEMPLATE_ID")
template_ids = [report_download_template_id]

report_download_content = "\n".join(
    [
        "(la version française suit)",
        "",
        "Hello ((name)),",
        "",
        "You requested a report of ''((report_name))''",
        "",
        "That report is now ready to download. To access it, visit ((service_name))''s [Delivery reports](((hyperlink_to_page_en)))",
        "",
        "We''ll delete the report in 72 hours.",
        "", 
        "The GC Notify Team",
        "",
        "---",
        "",
        "Bonjour ((name)),",
        "",
        "Vous avez demandé un rapport de ''((report_name)).''",
        "",
        "Ce rapport est maintenant disponible au téléchargement. Pour y accéder, visitez [les rapports](((hyperlink_to_page_fr))) de livraison de ((service_name)).",
        "",
        "Nous supprimerons le rapport dans 72 heures.",
        "",
        "L''équipe Notification GC",
        "",
    ]
)


def upgrade():
    template_insert = """
        INSERT INTO templates (id, name, template_type, created_at, content, archived, service_id, subject,
        created_by_id, version, process_type, hidden)
        VALUES ('{}', '{}', '{}', '{}', '{}', False, '{}', '{}', '{}', 1, '{}', false)
    """

    template_history_insert = """
        INSERT INTO templates_history (id, name, template_type, created_at, content, archived, service_id, subject,
        created_by_id, version, process_type, hidden)
        VALUES ('{}', '{}', '{}', '{}', '{}', False, '{}', '{}', '{}', 1, '{}', false)
    """

    template = {
        "id": report_download_template_id,
        "name": "Report ready to download",
        "subject": "Report ready to download | Rapport prêt à télécharger",
        "content": report_download_content,
    }

    op.execute(
        template_insert.format(
            template["id"],
            template["name"],
            "email",
            datetime.utcnow(),
            template["content"],
            current_app.config["NOTIFY_SERVICE_ID"],
            template["subject"],
            current_app.config["NOTIFY_USER_ID"],
            "normal",
        )
    )
    op.execute(
        template_history_insert.format(
            template["id"],
            template["name"],
            "email",
            datetime.utcnow(),
            template["content"],
            current_app.config["NOTIFY_SERVICE_ID"],
            template["subject"],
            current_app.config["NOTIFY_USER_ID"],
            "normal",
        )
    )


def downgrade():
    for template_id in template_ids:
        op.execute("DELETE FROM template_redacted WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM templates_history WHERE id = '{}'".format(template_id))
        op.execute("DELETE FROM templates WHERE id = '{}'".format(template_id))