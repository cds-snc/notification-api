"""
Revision ID: 0352_updated_at_default
Revises: 0351_user_service_roles
Create Date: 2022-11-02 19:54:18.568514
"""

from alembic import op
from sqlalchemy.dialects import postgresql

revision = '0352_updated_at_default'
down_revision = '0351_user_service_roles'


def upgrade():
    """
    https://stackoverflow.com/questions/33705697/alembic-integrityerror-column-contains-null-values-when-adding-non-nullable/53699748#53699748
    """

    # Update the ProviderDetails table.
    op.execute("UPDATE provider_details SET updated_at = '2022-11-04 16:21:33.638025' WHERE updated_at IS NULL")
    op.alter_column(
        'provider_details',
        'updated_at',
        existing_type=postgresql.TIMESTAMP(),
        existing_nullable=True,
        nullable=False
    )

    # Update the ProviderDetailsHistory table.
    op.execute("UPDATE provider_details_history SET updated_at = '2022-11-04 16:21:33.638025' WHERE updated_at IS NULL")
    op.alter_column(
        'provider_details_history',
        'updated_at',
        existing_type=postgresql.TIMESTAMP(),
        existing_nullable=True,
        nullable=False
    )


def downgrade():
    op.alter_column(
        'provider_details_history',
        'updated_at',
        existing_type=postgresql.TIMESTAMP(),
        existing_nullable=False,
        nullable=True
    )
    op.alter_column(
        'provider_details',
        'updated_at',
        existing_type=postgresql.TIMESTAMP(),
        existing_nullable=False,
        nullable=True
    )
