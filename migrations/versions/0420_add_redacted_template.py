"""empty message

Revision ID: 0420_add_redacted_template
Revises: 0419_add_forced_pass_template
Create Date: 2022-04-19 13:00:00

"""

import uuid

# revision identifiers, used by Alembic.
from datetime import datetime

from alembic import op

revision = "0420_add_redacted_template"
down_revision = "0419_add_forced_pass_template"

user_id = "6af522d0-2915-4e52-83a3-3690455a5fe6"
service_id = "d6aa2c68-a2d9-4437-ab19-3ae8eb202553"


def upgrade():
    op.get_bind()

    redacted_template_insert = """INSERT INTO template_redacted(template_id, redact_personalisation, updated_at, updated_by_id)
                                 VALUES ('{}', False, '{}', '{}')
                            """

    op.execute(
        redacted_template_insert.format(
            "e9a65a6b-497b-42f2-8f43-1736e43e13b3",
            datetime.utcnow(),
            user_id,
        )
    )


def downgrade():
    op.get_bind()
    op.execute("delete from template_redacted where template_id = '{}'".format("e9a65a6b-497b-42f2-8f43-1736e43e13b3"))
