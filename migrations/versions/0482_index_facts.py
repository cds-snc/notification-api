"""Add index to facts table

Revision ID: 0482_index_facts
Revises: 0481_report_ready_email
Create Date: 2025-04-09 12:00:00.000000

"""
from alembic import op

revision = "0482_index_facts"
down_revision = "0481_report_ready_email"

def index_exists(name):
    connection = op.get_bind()
    result = connection.execute(
        "SELECT exists(SELECT 1 from pg_indexes where indexname = '{}') as ix_exists;".format(name)
    ).first()
    return result.ix_exists


# option 1
def upgrade():
    op.execute("COMMIT")
    if not index_exists("ix_ft_notification_service_bst"):
        op.create_index(
            op.f("ix_ft_notification_service_bst"),
            "ft_notification_status",
            ["service_id", "bst_date"],
            postgresql_concurrently=True,
        )


def downgrade():
    op.execute("COMMIT")
    op.drop_index(
        op.f("ix_ft_notification_service_bst"), table_name="ft_notification_status", postgresql_concurrently=True
    )