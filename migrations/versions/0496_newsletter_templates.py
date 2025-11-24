"""

Revision ID: 0496_newsletter_templates
Revises: 0494_update_some_templates
Create Date: 2025-10-21 00:00:00

"""
from datetime import datetime

from alembic import op
from flask import current_app

revision = "0496_newsletter_templates"
down_revision = "0495_newsletter_conf_templates"

newsletter_template_en_id = current_app.config["NEWSLETTER_EMAIL_TEMPLATE_ID_EN"]
newsletter_template_fr_id = current_app.config["NEWSLETTER_EMAIL_TEMPLATE_ID_FR"]
template_ids = [newsletter_template_en_id, newsletter_template_fr_id]

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

    template_content_en = "\n".join(
        [
            "((newsletter_content))",
            "",
            "[Unsubscibe](((unsubscribe_link))) / [Change language](((change_language_link)))"
        ]
    )
    
    template_content_fr = "\n".join(
        [
            "((newsletter_content)) "
            "",
            "[Se désabonner](((unsubscribe_link))) / [Changer la langue](((change_language_link)))"
        ]
    )

    templates = [
        {
            "id": newsletter_template_en_id,
            "name": "EN Notify Newsletter",
            "subject": f"Newsletter ((newsletter_number))",
            "content": template_content_en,
            "template_type": "email",  
            "process_type": "normal",
        },
        {
            "id": newsletter_template_fr_id,
            "name": "EN Notify Newsletter",
            "subject": "Infolettre ((newsletter_number))",
            "content": template_content_fr,
            "template_type": "email",  
            "process_type": "normal",
        },
    ]

    for template in templates:
        op.execute(
            template_insert.format(
                template["id"],
                template["name"],
                template["template_type"],
                datetime.utcnow(),
                template["content"],
                current_app.config["NOTIFY_SERVICE_ID"],
                template["subject"],
                current_app.config["NOTIFY_USER_ID"],
                template["process_type"],
            )
        )

        op.execute(
            template_history_insert.format(
                template["id"],
                template["name"],
                template["template_type"],
                datetime.utcnow(),
                template["content"],
                current_app.config["NOTIFY_SERVICE_ID"],
                template["subject"],
                current_app.config["NOTIFY_USER_ID"],
                template["process_type"], 
            )
        )

def downgrade():
    for template_id in template_ids:
        op.execute("DELETE FROM notifications WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM notification_history WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM template_redacted WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM templates_history WHERE id = '{}'".format(template_id))
        op.execute("DELETE FROM templates WHERE id = '{}'".format(template_id))

