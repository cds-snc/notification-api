"""

Revision ID: 0151_refactor_letter_rates
Revises: 0150_another_letter_org
Create Date: 2017-12-05 10:24:41.232128

"""
import uuid
from datetime import datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0151_refactor_letter_rates"
down_revision = "0150_another_letter_org"


def upgrade():
    op.drop_table("letter_rate_details")
    op.drop_table("letter_rates")
    op.create_table(
        "letter_rates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("start_date", sa.DateTime(), nullable=False),
        sa.Column("end_date", sa.DateTime(), nullable=True),
        sa.Column("sheet_count", sa.Integer(), nullable=False),
        sa.Column("rate", sa.Numeric(), nullable=False),
        sa.Column("crown", sa.Boolean(), nullable=False),
        sa.Column("post_class", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    start_date = datetime(2016, 3, 31, 23, 00, 00)
    op.execute("insert into letter_rates values('{}', '{}', null, 1, 0.30, True, 'second')".format(str(uuid.uuid4()), start_date))
    op.execute("insert into letter_rates values('{}', '{}', null, 2, 0.33, True, 'second')".format(str(uuid.uuid4()), start_date))
    op.execute("insert into letter_rates values('{}', '{}', null, 3, 0.36, True, 'second')".format(str(uuid.uuid4()), start_date))

    op.execute(
        "insert into letter_rates values('{}', '{}', null, 1, 0.33, False, 'second')".format(str(uuid.uuid4()), start_date)
    )
    op.execute(
        "insert into letter_rates values('{}', '{}', null, 2, 0.39, False, 'second')".format(str(uuid.uuid4()), start_date)
    )
    op.execute(
        "insert into letter_rates values('{}', '{}', null, 3, 0.45, False, 'second')".format(str(uuid.uuid4()), start_date)
    )


def downgrade():
    op.drop_table("letter_rates")
    op.create_table(
        "letter_rates",
        sa.Column("id", postgresql.UUID(), autoincrement=False, nullable=False),
        sa.Column("valid_from", postgresql.TIMESTAMP(), autoincrement=False, nullable=False),
        sa.PrimaryKeyConstraint("id", name="letter_rates_pkey"),
        postgresql_ignore_search_path=False,
    )
    op.create_table(
        "letter_rate_details",
        sa.Column("id", postgresql.UUID(), autoincrement=False, nullable=False),
        sa.Column("letter_rate_id", postgresql.UUID(), autoincrement=False, nullable=False),
        sa.Column("page_total", sa.INTEGER(), autoincrement=False, nullable=False),
        sa.Column("rate", sa.NUMERIC(), autoincrement=False, nullable=False),
        sa.ForeignKeyConstraint(
            ["letter_rate_id"],
            ["letter_rates.id"],
            name="letter_rate_details_letter_rate_id_fkey",
        ),
        sa.PrimaryKeyConstraint("id", name="letter_rate_details_pkey"),
    )
