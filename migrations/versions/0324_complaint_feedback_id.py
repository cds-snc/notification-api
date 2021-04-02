"""

Revision ID: 0324_complaint_feedback_id
Revises: 0323_remove_inbound_number_index
Create Date: 2021-04-02 16:31:00

"""

from alembic import op

revision = '0324_complaint_feedback_id'
down_revision = '0323_remove_inbound_number_index'


def upgrade():
    op.alter_column('complaints', 'ses_feedback_id', nullable=True, new_column_name='feedback_id')


def downgrade():
    op.alter_column('complaints', 'feedback_id', nullable=True, new_column_name='ses_feedback_id')
