"""

Revision ID: 0453_set_supports_international
Revises: 0452_set_pgaudit_config
Create Date: 2024-06-20 14:36:03.038934

"""
from alembic import op

revision = "0453_set_supports_international"
down_revision = "0452_set_pgaudit_config"


def upgrade():
    op.execute("UPDATE provider_details SET supports_international=True WHERE identifier='sns'")
    op.execute("UPDATE provider_details SET supports_international=True WHERE identifier='pinpoint'")
    op.execute("UPDATE provider_details_history SET supports_international=True WHERE identifier='sns'")
    op.execute("UPDATE provider_details_history SET supports_international=True WHERE identifier='pinpoint'")


def downgrade():
    op.execute("UPDATE provider_details SET supports_international=False WHERE identifier='sns'")
    op.execute("UPDATE provider_details SET supports_international=False WHERE identifier='pinpoint'")
    op.execute("UPDATE provider_details_history SET supports_international=False WHERE identifier='sns'")
    op.execute("UPDATE provider_details_history SET supports_international=False WHERE identifier='pinpoint'")
