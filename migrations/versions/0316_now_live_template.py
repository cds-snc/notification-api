"""

Revision ID: 0316_now_live_template
Revises: 0315_lower_api_rate_limit
Create Date: 2021-02-11 11:20:12

"""
from alembic import op
from flask import current_app

revision = '0316_now_live_template'
down_revision = '0315_lower_api_rate_limit'

template_id = current_app.config['SERVICE_NOW_LIVE_TEMPLATE_ID']

def upgrade():
    template_subject = 'Your service is now live | Votre service est maintenant activé'
    
    template_content = '\n'.join([
            "Hello ((first name)),",
            '',
            '',
            "((Service name)) is now live on GC Notify.",
            '',
            "You’re all set to send notifications outside your team.",
            '',
            '',
            "You can send up to ((message_limit_en)) messages per day.",
            '',
            "If you ever need to send more messages, [contact us](((contact_us_url)) \"contact us\").",
            '',
            '',
            "[Sign in to GC Notify](((signin_url)) \"Sign in to GC Notify\")",
            '',
            "___",
            '',
            "Bonjour ((first name)),",
            '',
            '',
            "((Service name)) est maintenant activé sur GC Notification.",
            '',
            "Vous êtes prêts à envoyer des notifications en dehors de votre équipe.",
            '',
            '',
            "Vous pouvez envoyer jusqu’à ((message_limit_fr)) messages par jour.",
            '',
            "Si jamais vous avez besoin d’envoyer plus de messages, [communiquez avec nous](((contact_us_url)) \"communiquez avec nous\").",
            '',
            '',
            "[Connectez-vous à GC Notification](((signin_url)) \"Connectez-vous à GC Notification\")",
        ])

    op.execute("UPDATE templates SET content = '{}', subject = '{}' WHERE id = '{}'".format(template_content, template_subject, template_id))

def downgrade():
    pass
