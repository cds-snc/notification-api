"""

Revision ID: 0312_update_branding_request
Revises: 0311_disable_old_providers
Create Date: 2020-11-23 15:00:00

"""
from alembic import op
from flask import current_app

revision = '0312_update_branding_request'
down_revision = '0311_disable_old_providers'

template_id = current_app.config['BRANDING_REQUEST_TEMPLATE_ID']


def upgrade():
    template_content = '\n'.join([
        'A new logo has been uploaded by ((email)) for the following service:',
        '',
        "Service id: ((service_id))",
        "Service name: ((service_name))",
        '',
        "Logo filename: ((url))",
        '',
        '___',
        '',
        "Un nouveau logo a été téléchargé par ((email)) pour le service suivant :",
        '',
        "Identifiant du service : ((service_id))",
        "Nom du service : ((service_name))",
        '',
        "Nom du fichier du logo : ((url))",
    ])
    template_subject = "Branding change request for ((service_name)) | Demande de changement d''image de marque pour ((service_name))"

    op.execute("UPDATE templates SET content = '{}', subject = '{}' WHERE id = '{}'".format(template_content, template_subject, template_id))
    op.execute("UPDATE templates_history SET content = '{}', subject = '{}' WHERE id = '{}'".format(template_content, template_subject, template_id))


def downgrade():
    pass
