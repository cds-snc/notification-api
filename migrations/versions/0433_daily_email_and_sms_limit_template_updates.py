"""

Revision ID: 0423_daily_email_limit_updated
Revises: 0422_add_billable_units
Create Date: 2022-09-21 00:00:00

"""
from datetime import datetime

from alembic import op
from flask import current_app

revision = "0433_daily_email_and_sms_limit_template_updates"
down_revision = "0432_daily_email_limit_templates"

near_email_limit_template_id = current_app.config["NEAR_DAILY_EMAIL_LIMIT_TEMPLATE_ID"]
at_email_limit_template_id = current_app.config["REACHED_DAILY_EMAIL_LIMIT_TEMPLATE_ID"]
daily_email_limit_updated_id = current_app.config["DAILY_EMAIL_LIMIT_UPDATED_TEMPLATE_ID"]

email_template_ids = [near_email_limit_template_id, at_email_limit_template_id, daily_email_limit_updated_id]

near_sms_limit_template_id = current_app.config["NEAR_DAILY_SMS_LIMIT_TEMPLATE_ID"]
at_sms_limit_template_id = current_app.config["REACHED_DAILY_SMS_LIMIT_TEMPLATE_ID"]
daily_sms_limit_updated_id = current_app.config["DAILY_SMS_LIMIT_UPDATED_TEMPLATE_ID"]

sms_template_ids = [near_sms_limit_template_id, at_sms_limit_template_id, daily_sms_limit_updated_id]


templates = [{
"id": near_email_limit_template_id,
"name": "Near dailly SMS limit",
"template_type": "sms",
"content": """Hello ((name)),

((service_name)) can send ((message_limit_en)) emails per day. You''ll be blocked from sending if you exceed that limit before 7pm Eastern Time. [Check your current local time.](https://nrc.canada.ca/en/web-clock/)

To request a limit increase, [contact us](https://notification.canada.ca/contact). We''ll respond within 1 business day.

The GC Notify team
---
Bonjour ((name)),

La limite quotidienne d''envoi est de ((message_limit_fr)) courriels par jour pour ((service_name)). Si vous dépassez cette limite avant 19 heures, heure de l''Est, vos envois seront bloqués.

[Comparez les heures officielles au Canada.](https://nrc.canada.ca/fr/horloge-web/)

Veuillez [nous contacter](https://notification.canada.ca/contact) si vous souhaitez augmenter votre limite d''envoi. Nous vous répondrons en un jour ouvrable.

L''équipe Notification GC
""",
"subject": "((service_name)) is near its daily limit for emails. | ",
"process_type": "normal",
}]

lol = "La limite quotidienne d''envoi de courriels est presque atteinte pour ((service_name))."


def upgrade():
    conn = op.get_bind()

    for template in templates:
        current_version = conn.execute("select version from templates where id='{}'".format(template["id"])).fetchone()
        template["version"] = current_version[0] + 1

    template_update = """
        UPDATE templates SET content = '{}', subject = '{}', version = '{}', updated_at = '{}'
        WHERE id = '{}'
    """

    for template in templates:
        # import pdb; pdb.set_trace()
        # print(template_update.format(
        #         template["content"],
        #         template["subject"],
        #         template["version"],
        #         datetime.utcnow(),
        #         template["id"],
        #         ))

        op.execute(
            template_update.format(
                template["content"],
                template["subject"],
                template["version"],
                datetime.utcnow(),
                template["id"],
            )
        )

def downgrade():
    pass