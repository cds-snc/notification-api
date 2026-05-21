"""
Revision ID: 0514_add_files_table
Revises: 0513_backfill_api_key_perm
Create Date: 2026-05-21

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0514_add_files_table'
down_revision = '0513_backfill_api_key_perm'

def upgrade():
    op.create_table(
        'files',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column('template_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('templates.id'), nullable=False),
        sa.Column('service_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('services.id'), nullable=False),
        sa.Column('document_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('type', sa.Enum('attach', 'link', 'template', name='notify_file_type_enum'), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('mime_type', sa.Text(), nullable=True),
        sa.Column('file_size', sa.Integer(), nullable=True),
        sa.Column('status', sa.Enum('pending_virus_scan', 'uploaded', 'virus_scan_failed', 'deleted', name='notify_file_status_enum'), nullable=False),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_files_template_id', 'files', ['template_id'])
    op.create_index('ix_files_service_id', 'files', ['service_id'])

def downgrade():
    op.drop_index('ix_files_service_id', table_name='files')
    op.drop_index('ix_files_template_id', table_name='files')
    op.drop_table('files')
    file_type_enum = postgresql.ENUM('attach', 'link', 'template', name='notify_file_type_enum')
    file_status_enum = postgresql.ENUM('pending_virus_scan', 'uploaded', 'virus_scan_failed', 'deleted', name='notify_file_status_enum')
    file_type_enum.drop(op.get_bind(), checkfirst=True)
    file_status_enum.drop(op.get_bind(), checkfirst=True)
