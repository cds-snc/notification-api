"""Add billable_units to jobs so scheduled SMS jobs can be counted towards the daily limit of the day they're sent.

Revision ID: 0527_jobs_billable_units
Revises: 0526_sched_notifs_one_table
Create Date: 2026-11-12

Scheduled jobs are counted towards the daily limit of the day they're scheduled for, when that day's count is
loaded from the database. For SMS that needs the number of fragments in the job, which isn't otherwise stored.
"""

import sqlalchemy as sa
from alembic import op

revision = "0527_jobs_billable_units"
down_revision = "0526_sched_notifs_one_table"


def upgrade():
    op.add_column("jobs", sa.Column("billable_units", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("jobs", "billable_units")
