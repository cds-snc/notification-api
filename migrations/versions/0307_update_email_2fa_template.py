"""

Revision ID: 0307_update_email_2fa_template
Revises: 0306c_branding_organisation
Create Date: 2020-06-10 08:08:00

"""
from datetime import datetime

from alembic import op


revision = '0307_update_email_2fa_template'
down_revision = '0306c_branding_organisation'

template_id = '299726d2-dba6-42b8-8209-30e1d66ea164'


def upgrade():
    template_content = '\n'.join([
        'Hi ((name)),',
        '',
        '((verify_code)) is your security code to log in to Notify.',
        '',
        '-------',
        '',
        '',
        'Bonjour ((name)),',
        '',
        '((verify_code)) est votre code de sécurité pour vous connecter à Notification.',
    ])
    template_subject = 'Sign in to Notify  |  Inscrivez-vous dans Notification'
    op.execute("UPDATE templates SET content = '{}', subject = '{}' WHERE id = '{}'".format(template_content, template_subject, template_id))
    op.execute("UPDATE templates_history SET content = '{}', subject = '{}' WHERE id = '{}'".format(template_content, template_subject, template_id))


def downgrade():
    template_content = '\n'.join([
        'Hi ((name)),',
        '\n',
        'To sign in to Notify please open this link:',
        '((url))',
        '\n',
        '-------',
        '\n',
        '\n',
        'Bonjour ((name)),',
        '\n',
        'Pour vous connecter à Notification, veuillez ouvrir ce lien: ((url))',
    ])

    op.execute("UPDATE templates SET content = '{}' WHERE id = '{}'".format(template_content, template_id))
    op.execute("UPDATE templates_history SET content = '{}' WHERE id = '{}'".format(template_content, template_id))
