"""

Revision ID: 0484_users_migrations
Revises: 0483_index_jobs
Create Date: 2025-06-09 20:01:02.943393

"""
from alembic import op
import sqlalchemy as sa

revision = '0484_users_migrations'
down_revision = '0483_index_jobs'


def upgrade():
    op.add_column("users", sa.Column("verified_phonenumber", sa.Boolean, server_default='true', nullable=True))
    op.execute("UPDATE users SET verified_phonenumber = true")
    

def downgrade():
    op.drop_column("users", "verified_phonenumber")