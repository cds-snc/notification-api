"""

Revision ID: 0305e_account_change_type
Revises: 0305d_block_users
Create Date: 2019-11-20 17:08:21.019759

"""
from flask import current_app
from alembic import op

revision = '0305e_account_change_type'
down_revision = '0305d_block_users'

templates = [
    {
        'id': current_app.config['ACCOUNT_CHANGE_TEMPLATE_ID'],
        'name': 'Account update',
        'content_lines': [
            'Your user account information was changed on ((base_url)). ',
            '',
            'Updated information: ((change_type))',
            '',
            'If you did not make this change, contact us immediately using the following link:',
            '',
            '((contact_us_url))',
        ],
    },
]

content = '\n'.join(templates[0]['content_lines'])

sql = """
        UPDATE {}
        SET content = '{}', updated_at = now()
        WHERE id='{}'
        """;

def upgrade():
    op.execute(sql.format('templates', content, templates[0]['id']))
    op.execute(sql.format('templates_history', content, templates[0]['id']))

def downgrade():
  pass
