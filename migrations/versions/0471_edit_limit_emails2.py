"""empty message

Revision ID: 0471_edit_limit_emails2
Revises: 0470_change_default_limit
Create Date: 2016-06-01 14:17:01.963181

"""

from datetime import datetime

from alembic import op
from flask import current_app

revision = "0471_edit_limit_emails2"
down_revision = "0470_change_default_limit"


near_annual_limit_template_id = current_app.config["NEAR_ANNUAL_LIMIT_TEMPLATE_ID"]
reached_annual_limit_template_id = current_app.config["REACHED_ANNUAL_LIMIT_TEMPLATE_ID"]
annual_limit_updated_template_id = current_app.config["ANNUAL_LIMIT_UPDATED_TEMPLATE_ID"]
status_template_category_id = "55eb1137-6dc6-4094-9031-f61124a279dc"
information_template_category_id = "207b293c-2ae5-48e8-836d-fcabd60b2153"
template_ids = [
    near_annual_limit_template_id,
    reached_annual_limit_template_id,
    annual_limit_updated_template_id,
]

annual_limit_updated = "\n".join(
    [
        "(la version française suit)",
        "",
        "Hello ((name)),",
        "",
        "You can now send ((message_limit_en)) ((message_type_en)) per fiscal year.",
        "",
        "For more information, visit the usage report for your [service](((hyperlink_to_page_en))).",
        "",
        "The GC Notify Team",
        "",
        "---",
        "",
        "Bonjour ((name)),",
        "",
        "Vous pouvez maintenant envoyer ((message_limit_fr)) ((message_type_fr)) par exercice financier.",
        "",
        "Pour en savoir plus, consultez le rapport d’utilisation pour votre [service](((hyperlink_to_page_fr))).",
        "",
        "L’équipe Notification GC",
    ]
)

annual_limit_reached = "\n".join(
    [
        "(la version française suit)",
        "",
        "Hello ((name)),",
        "",
        "0 ((message_type_en)) remaining until April ((fiscal_end)).",
        "",
        "GC Notify has annual and daily sending limits. This message is about your annual limit.",
        "We’ve paused ((message_type_en)) sending until your limit resets on April 1, ((fiscal_end)).",
        "",
        "For more information, visit the usage report for your [service](((hyperlink_to_page_en))).",
        "",
        "The GC Notify team",
        "",
        "---",
        "",
        "Bonjour ((name)),",
        "",
        "0 ((message_type_fr)) restant d’ici avril ((fiscal_end)).",
        "",
        "Le service Notification GC comporte des limites annuelles et quotidiennes. Ce message concerne votre limite annuelle.",
        "Nous avons suspendu l’envoi de ((message_type_fr)) jusqu’à la réinitialisation de votre limite le 1er avril ((fiscal_end)).",
        "",
        "Pour en savoir plus, consultez le rapport d’utilisation pour [votre service](((hyperlink_to_page_fr))).",
        "",
        "L’équipe Notification GC",
        "",
    ]
)

near_annual_limit = "\n".join(
    [
        "(la version française suit)",
        "",
        "Hello ((name)),",
        "",
        "GC Notify has annual and daily sending limits. This message is about your annual limit.",
        "",
        "((service_name)) has sent ((count_en)) out of its limit of ((message_limit_en)) ((message_type_en)) per fiscal year.",
        "((service_name)) has ((remaining_en)) ((message_type_en)) remaining until April 1, ((fiscal_end)).",
        "",
        "For more information, visit the usage report for your [service](((hyperlink_to_page_en))).",
        "",
        "The GC Notify Team",
        "",
        "---",
        "",
        "Bonjour ((name)),",
        "",
        "Le service Notification GC comporte des limites annuelles et quotidiennes. Ce message concerne votre limite annuelle.",
        "",
        "((service_name)) a envoyé ((count_fr)) ((message_type_fr)) et sa limite d’envoi est fixée à ((message_limit_fr)) ((message_type_fr)) par exercice financier.",
        "((service_name)) peut encore envoyer ((remaining_fr)) ((message_type_fr)) d’ici le 1er avril ((fiscal_end)).",
        "",
        "Pour en savoir plus, consultez le rapport d’utilisation pour votre [service](((hyperlink_to_page_fr))).",
        "",
        "L’équipe Notification GC",
        "",
    ]
)


def upgrade():
    conn = op.get_bind()

    templates = [
        {
            "id": near_annual_limit_template_id,
            "name": "Near annual limit",
            "subject": " Alert for ((service_name)) | # Alerte pour ((service_name)).",
            "content": near_annual_limit,
            "template_category_id": status_template_category_id,
        },
        {
            "id": reached_annual_limit_template_id,
            "name": "Annual limit reached",
            "subject": "Alert for ((service_name)) | # Alerte pour ((service_name))",
            "content": annual_limit_reached,
            "template_category_id": status_template_category_id,
        },
        {
            "id": annual_limit_updated_template_id,
            "name": "Annual limit updated",
            "subject": "Annual limit update for ((service_name)) | Nous avons mis à jour la limite annuelle pour ((service_name))",
            "content": annual_limit_updated,
            "template_category_id": status_template_category_id,
        },
    ]

    template_update = """
        UPDATE templates SET content = '{}', subject = '{}', version = '{}', updated_at = '{}', template_category_id = '{}'
        WHERE id = '{}'
    """
    template_history_insert = """
        INSERT INTO templates_history (id, name, template_type, created_at, content, archived, service_id, subject,
        created_by_id, version, hidden, template_category_id)
        VALUES ('{}', '{}', '{}', '{}', '{}', False, '{}', '{}', '{}', {}, false, '{}')
    """

    for template in templates:
        current_version = conn.execute("select version from templates where id='{}'".format(template["id"])).fetchone()
        name = conn.execute("select name from templates where id='{}'".format(template["id"])).fetchone()
        template["version"] = current_version[0] + 1
        template["name"] = name[0]
        op.execute(
            template_update.format(
                template["content"],
                template["subject"],
                template["version"],
                datetime.utcnow(),
                template["template_category_id"],
                template["id"],
            )
        )
        op.execute(
            template_history_insert.format(
                template["id"],
                template["name"],
                "email",
                datetime.utcnow(),
                template["content"],
                current_app.config["NOTIFY_SERVICE_ID"],
                template["subject"],
                current_app.config["NOTIFY_USER_ID"],
                template["version"],
                template["template_category_id"],
            )
        )


def downgrade():
    pass
