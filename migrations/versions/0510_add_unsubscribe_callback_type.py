"""Seed service_callback_type with 'unsubscribe' type.

Revision ID: 0510_add_unsubscribe_callback_type
Revises: 0509_unsubscribe_requests
Create Date: 2026-03-24 00:00:00
"""
from alembic import op

revision = "0510_add_unsubscribe_callback_type"
down_revision = "0509_unsubscribe_requests"


def upgrade():
    op.execute("INSERT INTO service_callback_type (name) VALUES ('unsubscribe') ON CONFLICT DO NOTHING")


def downgrade():
    op.execute("DELETE FROM service_callback_type WHERE name = 'unsubscribe'")
