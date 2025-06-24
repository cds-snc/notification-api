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
    # PostgreSQL requires that CREATE INDEX CONCURRENTLY cannot run within a transaction.
    # Alembic runs migrations in a transaction by default, so we need to commit the current
    # transaction before creating indexes concurrently.
    op.execute("COMMIT")
    if not index_exists("ix_jobs_created_at"):
        op.create_index(
            op.f('ix_jobs_created_at'), 
            'jobs', 
            ['created_at'], 
            unique=False, 
            postgresql_concurrently=True
        )
    if not index_exists("ix_jobs_processing_started"):
        op.create_index(
            op.f('ix_jobs_processing_started'), 
            'jobs', 
            ['processing_started'], 
            unique=False, 
            postgresql_concurrently=True
        )


def downgrade():
    # PostgreSQL requires that DROP INDEX CONCURRENTLY cannot run within a transaction.
    # Need to commit the current transaction first.
    op.execute("COMMIT")
    if index_exists("ix_jobs_processing_started"):
        op.drop_index(
            op.f('ix_jobs_processing_started'), 
            table_name='jobs', 
            postgresql_concurrently=True
        )
    if index_exists("ix_jobs_created_at"):
        op.drop_index(
            op.f('ix_jobs_created_at'), 
            table_name='jobs', 
            postgresql_concurrently=True
        )
