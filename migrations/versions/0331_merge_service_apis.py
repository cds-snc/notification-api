"""
Revision ID: 0331_merge_service_apis
Revises: 0330a_grant_edit_templates
Create Date: 2021-07-01
"""

import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import JSONB

from app.models import NOTIFICATION_STATUS_TYPES_COMPLETED

revision = '0331_merge_service_apis'
down_revision = '0330a_grant_edit_templates'


def upgrade():
    op.execute(('INSERT INTO service_callback_type values(\'inbound_sms\')'))
    op.execute((
        'INSERT INTO service_callback_api (id, service_id, url, bearer_token, created_at, updated_at, updated_by_id, version, callback_type, notification_statuses)'
        'SELECT id, service_id, url, bearer_token, created_at, updated_at, updated_by_id, version, \'inbound_sms\', \'{}\' FROM service_inbound_api'))

    op.drop_index('ix_service_inbound_api_service_id', table_name='service_inbound_api', if_exists=True)
    op.drop_index('ix_service_inbound_api_updated_by_id', table_name='service_inbound_api', if_exists=True)
    op.drop_table('service_inbound_api')

    op.rename_table('service_callback_api', 'service_callback')

    op.execute((
        'INSERT INTO service_callback_api_history (id, service_id, url, bearer_token, created_at, updated_at, updated_by_id, version, callback_type, notification_statuses)'
        'SELECT id, service_id, url, bearer_token, created_at, updated_at, updated_by_id, version, \'inbound_sms\', \'{}\' FROM service_inbound_api_history'))

    op.drop_table('service_inbound_api_history')
    op.rename_table('service_callback_api_history', 'service_callback_history')


def downgrade():
    op.rename_table('service_callback', 'service_callback_api')
    op.create_table('service_inbound_api',
                    sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
                    sa.Column('service_id', postgresql.UUID(as_uuid=True), nullable=False),
                    sa.Column('url', sa.String(), nullable=False),
                    sa.Column('bearer_token', sa.String(), nullable=False),
                    sa.Column('created_at', sa.DateTime(), nullable=False),
                    sa.Column('updated_at', sa.DateTime(), nullable=True),
                    sa.Column('updated_by_id', postgresql.UUID(as_uuid=True), nullable=False),
                    sa.Column('version', sa.Integer(), nullable=False),
                    sa.ForeignKeyConstraint(['service_id'], ['services.id'], ),
                    sa.ForeignKeyConstraint(['updated_by_id'], ['users.id'], ),
                    sa.PrimaryKeyConstraint('id')
                    )

    op.execute((
        'INSERT INTO service_inbound_api (id, service_id, url, bearer_token, created_at, updated_at, updated_by_id, version)'
        'SELECT id, service_id, url, bearer_token, created_at, updated_at, updated_by_id, version FROM service_callback_api WHERE callback_type = \'inbound_sms\''))

    op.execute('DELETE FROM service_callback_api WHERE callback_type = \'inbound_sms\'')

    op.rename_table('service_callback_history', 'service_callback_api_history')
    op.create_table('service_inbound_api_history',
                    sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
                    sa.Column('service_id', postgresql.UUID(as_uuid=True), nullable=False),
                    sa.Column('url', sa.String(), nullable=False),
                    sa.Column('bearer_token', sa.String(), nullable=False),
                    sa.Column('created_at', sa.DateTime(), nullable=False),
                    sa.Column('updated_at', sa.DateTime(), nullable=True),
                    sa.Column('updated_by_id', postgresql.UUID(as_uuid=True), nullable=False),
                    sa.Column('version', sa.Integer(), nullable=False),
                    sa.ForeignKeyConstraint(['service_id'], ['services.id'], ),
                    sa.ForeignKeyConstraint(['updated_by_id'], ['users.id'], ),
                    sa.PrimaryKeyConstraint('id')
                    )

    op.execute((
        'INSERT INTO service_inbound_api_history (id, service_id, url, bearer_token, created_at, updated_at, updated_by_id, version)'
        'SELECT id, service_id, url, bearer_token, created_at, updated_at, updated_by_id, version FROM service_callback_api_history WHERE callback_type = \'inbound_sms\''))

    op.execute('DELETE FROM service_callback_api_history WHERE callback_type = \'inbound_sms\'')
    op.execute('DELETE FROM service_callback_type WHERE name = \'inbound_sms\'')

