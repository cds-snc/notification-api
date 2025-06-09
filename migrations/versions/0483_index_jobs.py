"""

Revision ID: 0483_index_jobs
Revises: 0482_index_facts
Create Date: 2025-06-09 20:01:02.943393

"""
from alembic import op

revision = '0483_index_jobs'
down_revision = '0482_index_facts'

def index_exists(name):
    connection = op.get_bind()
    result = connection.execute(
        "SELECT exists(SELECT 1 from pg_indexes where indexname = '{}') as ix_exists;".format(name)
    ).first()
    return result.ix_exists

def upgrade():
    if not index_exists("ix_jobs_created_at"):
        op.create_index(op.f('ix_jobs_created_at'), 'jobs', ['created_at'], unique=False)
    if not index_exists("ix_jobs_processing_started"):
        op.create_index(op.f('ix_jobs_processing_started'), 'jobs', ['processing_started'], unique=False)


def downgrade():
    if index_exists("ix_jobs_processing_started"):
        op.drop_index(op.f('ix_jobs_processing_started'), table_name='jobs')
    if index_exists("ix_jobs_created_at"):
        op.drop_index(op.f('ix_jobs_created_at'), table_name='jobs')
