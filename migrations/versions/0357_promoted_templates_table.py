"""

Revision ID: 0357_promoted_templates_table
Revises: 0356_add_include_payload
Create Date: 2023-03-15 22:24:20.449284

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0357_promoted_templates_table'
down_revision = '0356_add_include_payload'


def upgrade():
    op.create_table('promoted_templates',
    sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('service_id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('template_id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('promoted_service_id', postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column('promoted_template_id', postgresql.UUID(as_uuid=True), nullable=True),
    sa.Column('promoted_template_content_digest', sa.Text(), nullable=True),
    sa.Column('promoted_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['service_id'], ['services.id'], ),
    sa.ForeignKeyConstraint(['template_id'], ['templates.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_promoted_templates_service_id'), 'promoted_templates', ['service_id'], unique=False)
    op.create_index(op.f('ix_promoted_templates_template_id'), 'promoted_templates', ['template_id'], unique=False)



def downgrade():
    op.drop_index(op.f('ix_promoted_templates_service_id'), table_name='promoted_templates')
    op.drop_index(op.f('ix_promoted_templates_template_id'), table_name='promoted_templates')
    op.drop_table('promoted_templates')
