"""

Revision ID: 0476_add_reports_table
Revises: 0475_change_notification_status
Create Date: 2025-03-19 20:10:55.451309

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0476_add_reports_table'
down_revision = '0475_change_notification_status'


def upgrade():
    op.create_table('reports',
    sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('report_type', sa.String(length=255), nullable=False),
    sa.Column('requested_at', sa.DateTime(), nullable=False),
    sa.Column('completed_at', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=True),
    sa.Column('requesting_user_id', postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column('service_id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('job_id', postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column('url', sa.String(length=255), nullable=True),
    sa.Column('status', sa.String(length=255), nullable=False),
    sa.ForeignKeyConstraint(['job_id'], ['jobs.id'], ),
    sa.ForeignKeyConstraint(['requesting_user_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['service_id'], ['services.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_reports_service_id'), 'reports', ['service_id'], unique=False)
    

def downgrade():
    op.drop_index(op.f('ix_reports_service_id'), table_name='reports')
    op.drop_table('reports')
