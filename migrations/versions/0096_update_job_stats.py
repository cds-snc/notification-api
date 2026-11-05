"""empty message

Revision ID: 0096_update_job_stats
Revises: 0095_migrate_existing_svc_perms
Create Date: 2017-06-08 15:46:49.637642

"""

# revision identifiers, used by Alembic.
revision = "0096_update_job_stats"
down_revision = "0095_migrate_existing_svc_perms"

from alembic import op


def upgrade():
    query = (
        "UPDATE job_statistics  "
        "set sent = sms_sent + emails_sent + letters_sent, "
        " delivered = sms_delivered + emails_delivered, "
        " failed = sms_failed + emails_failed + letters_failed "
    )

    conn = op.get_bind()
    conn.exec_driver_sql(query)


def downgrade():
    query = "UPDATE job_statistics  " "set sent = 0, " " delivered = 0, " " failed = 0 "

    conn = op.get_bind()
    conn.exec_driver_sql(query)
