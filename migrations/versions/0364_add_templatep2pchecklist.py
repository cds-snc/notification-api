"""

Revision ID: 0364_add_templatep2pchecklist
Revises: 0363_add_reply_to_inbox
Create Date: 2023-10-17 22:52:47.268549

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0364_add_templatep2pchecklist'
down_revision = '0363_add_reply_to_inbox'


def upgrade():
    op.create_table('template_p2p_checklist',
    sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('template_id', postgresql.UUID(as_uuid=True), nullable=False),
    sa.Column('checklist', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['template_id'], ['templates.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_template_p2p_checklist_template_id'), 'template_p2p_checklist', ['template_id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_template_p2p_checklist_template_id'), table_name='template_p2p_checklist')
    op.drop_table('template_p2p_checklist')

