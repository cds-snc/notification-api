"""empty message

Revision ID: 0006_api_keys_history
Revises: 0005_add_provider_stats
Create Date: 2016-04-20 17:21:38.541766

"""

# revision identifiers, used by Alembic.
revision = "0006_api_keys_history"
down_revision = "0005_add_provider_stats"

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


def upgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "api_keys_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("secret", sa.String(length=255), nullable=False),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expiry_date", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("version", sa.Integer(), autoincrement=False, nullable=False),
        sa.PrimaryKeyConstraint("id", "version"),
    )

    op.create_index(
        op.f("ix_api_keys_history_created_by_id"),
        "api_keys_history",
        ["created_by_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_api_keys_history_service_id"),
        "api_keys_history",
        ["service_id"],
        unique=False,
    )
    op.add_column("api_keys", sa.Column("created_at", sa.DateTime(), nullable=True))
    op.add_column(
        "api_keys",
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("api_keys", sa.Column("updated_at", sa.DateTime(), nullable=True))
    op.add_column("api_keys", sa.Column("version", sa.Integer(), nullable=True))

    op.get_bind()
    op.execute(
        "UPDATE api_keys SET created_by_id = (SELECT user_id FROM user_to_service WHERE api_keys.service_id = user_to_service.service_id LIMIT 1)"
    )
    op.execute("UPDATE api_keys SET version = 1, created_at = now()")
    op.execute(
        "INSERT INTO api_keys_history (id, name, secret, service_id, expiry_date, created_at, updated_at, created_by_id, version) SELECT id, name, secret, service_id, expiry_date, created_at, updated_at, created_by_id, version FROM api_keys"
    )

    op.alter_column("api_keys", "created_at", nullable=False)
    op.alter_column("api_keys", "created_by_id", nullable=False)
    op.alter_column("api_keys", "version", nullable=False)

    op.create_index(op.f("ix_api_keys_created_by_id"), "api_keys", ["created_by_id"], unique=False)
    op.create_foreign_key("fk_api_keys_created_by_id", "api_keys", "users", ["created_by_id"], ["id"])
    ### end Alembic commands ###


def downgrade():
    ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint("fk_api_keys_created_by_id", "api_keys", type_="foreignkey")
    op.drop_index(op.f("ix_api_keys_created_by_id"), table_name="api_keys")
    op.drop_column("api_keys", "version")
    op.drop_column("api_keys", "updated_at")
    op.drop_column("api_keys", "created_by_id")
    op.drop_column("api_keys", "created_at")
    op.drop_index(op.f("ix_api_keys_history_service_id"), table_name="api_keys_history")
    op.drop_index(op.f("ix_api_keys_history_created_by_id"), table_name="api_keys_history")
    op.drop_table("api_keys_history")
    ### end Alembic commands ###
