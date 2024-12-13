"""empty message

Revision ID: 0470_change_default_limit
Revises: 0469_edit_emails
Create Date: 2016-06-01 14:17:01.963181

"""
revision = "0470_change_default_limit"
down_revision = "0469_edit_emails"

from alembic import op


def upgrade():
    conn = op.get_bind()
    conn.execute("ALTER TABLE services ALTER COLUMN email_annual_limit SET DEFAULT 20000000")
    conn.execute("ALTER TABLE services ALTER COLUMN sms_annual_limit SET DEFAULT 100000")
    conn.execute("UPDATE services SET email_annual_limit = 20000000 WHERE email_annual_limit = 10000000")
    conn.execute("UPDATE services SET sms_annual_limit = 100000 WHERE sms_annual_limit = 25000")


def downgrade():
    conn = op.get_bind()
    conn.execute("ALTER TABLE services ALTER COLUMN email_annual_limit SET DEFAULT 10000000")
    conn.execute("ALTER TABLE services ALTER COLUMN sms_annual_limit SET DEFAULT 25000")
