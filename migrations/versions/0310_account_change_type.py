"""

Revision ID: 0310_account_change_type
Revises: 0305e_account_change_type
Create Date: 2020-09-16 15:47:21.019759

"""
from flask import current_app
from alembic import op

revision = '0310_account_change_type'
down_revision = '0309_system_templates_priority'

template = {
    'id': current_app.config['ACCOUNT_CHANGE_TEMPLATE_ID'],
    'subject': 'Account information changed | Informations de compte modifiées',
    'content_lines': [
        'Your GC Notify user account information was changed on ((base_url)).',
        '',
        'Updated information: ((change_type_en))',
        '',
        'If you did not make this change, [contact us](((contact_us_url)) "contact us") immediately.',
        '',
        '___',
        '',
        "Les informations de votre compte d''utilisateur ont été modifiées sur ((base_url)).",
        '',
        "Informations mises à jour : ((change_type_fr))",
        '',
        "Si vous n''avez pas effectué ce changement, [communiquez avec nous](((contact_us_url)) \"communiquez avec nous\") immédiatement.",
    ]
}

content = '\n'.join(template['content_lines'])
subject = template['subject']

sql = """
    UPDATE {}
    SET content = '{}', subject = '{}', updated_at = now()
    WHERE id='{}'
"""


def upgrade():
    op.execute(sql.format('templates', content, subject, template['id']))
    op.execute(sql.format('templates_history', content, subject, template['id']))


def downgrade():
    pass
