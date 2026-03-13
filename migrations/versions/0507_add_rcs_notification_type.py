"""
Revision ID: 0507_add_rcs_notification_type
Revises: 0506_update_ft_billing
Create Date: 2026-03-05 00:00:00

Add a new notification type enumeration value for RCS.
"""
from alembic import op

revision = "0507_add_rcs_notification_type"
down_revision = "0506_update_ft_billing"


def upgrade():
    # prevent from being executed in a transaction block
    op.execute("COMMIT")

    # Add a new notification type enumeration value for RCS
    op.execute("ALTER TYPE notification_type ADD VALUE 'rcs'")
    op.execute("ALTER TYPE template_type ADD VALUE 'rcs'")
    op.execute("INSERT INTO service_permission_types (name) VALUES ('rcs') ON CONFLICT DO NOTHING")


def downgrade():
    # Remove the RCS notification type enumeration value
    sql = f"""DELETE FROM pg_enum
            WHERE enumlabel = 'rcs'
            AND enumtypid = (
              SELECT oid FROM pg_type WHERE typname = 'notification_type'
            )"""
    op.execute(sql)
    
    sql = f"""DELETE FROM pg_enum
            WHERE enumlabel = 'rcs'
            AND enumtypid = (
              SELECT oid FROM pg_type WHERE typname = 'template_type'
            )"""
    op.execute(sql)
    
    sql = f"""DELETE FROM service_permission_types WHERE name = 'rcs'"""
    op.execute(sql)
