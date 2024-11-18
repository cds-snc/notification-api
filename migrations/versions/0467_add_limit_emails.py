"""empty message

Revision ID: 0467_add_limit_emails
Revises: 0466_add_cypress_data
Create Date: 2016-06-01 14:17:01.963181

"""

from datetime import datetime

from alembic import op
from flask import current_app

revision = "0467_add_limit_emails"
down_revision = "0466_add_cypress_data"

near_annual_limit_template_id = current_app.config["NEAR_ANNUAL_LIMIT_TEMPLATE_ID"]
reached_annual_limit_template_id = current_app.config["REACHED_ANNUAL_LIMIT_TEMPLATE_ID"]
annual_limit_updated_template_id = current_app.config["ANNUAL_LIMIT_UPDATED_TEMPLATE_ID"]
quarterly_annual_limit_template_id = current_app.config["ANNUAL_LIMIT_QUARTERLY_USAGE_TEMPLATE_ID"]
template_ids = [
    near_annual_limit_template_id,
    reached_annual_limit_template_id,
    annual_limit_updated_template_id,
    quarterly_annual_limit_template_id,
]

annual_limit_reached = "\n".join(
    [
        "(la version française suit)",
        "",
        "Hello ((name)),",
        "",
        "0 ((message_type)) remaining until April  ((fiscal_end)).",
        "",
        "GC Notify has annual and daily sending limits. This message is about your annual limit.",
        "We’ve paused ((message_type)) sending until your limit resets on April 1, ((fiscal_end)).",
        "",
        "For more information, visit the usage report for your [service]((hyperlink_to_page_en)).",
        "",
        "The GC Notify team",
        "",
        "---",
        "",
        "Bonjour ((name)),",
        "",
        "0 ((message_type)) restant d’ici avril ((fiscal_end)).",
        "",
        "Le service Notification GC comporte des limites annuelles et quotidiennes. Ce message concerne votre limite annuelle.",
        "Nous avons suspendu l’envoi de ((message_type)) jusqu’à la réinitialisation de votre limite le 1er avril ((fiscal_end)).",
        "",
        "Pour en savoir plus, consultez le rapport d’utilisation pour [votre service]((hyperlink_to_page_fr)).",
        "",
        "L’équipe Notification GC",
        "",
    ]
)

annual_limit_updated = "\n".join(
    [
        "(la version française suit)",
        "",
        "Hello ((name)),",
        "",
        "You can now send ((message_limit_en))((message_type)) messages per fiscal year.",
        "",
        "For more information, visit the usage report for your [service]((hyperlink_to_page_en)).",
        "",
        "The GC Notify Team",
        "",
        "---",
        "",
        "Bonjour ((name)),",
        "",
        "Vous pouvez maintenant envoyer ((message_limit_en)) ((message_type)) par exercice financier.",
        "",
        "Pour en savoir plus, consultez le rapport d’utilisation pour votre [service]((hyperlink_to_page_fr)).",
        "",
        "L’équipe Notification GC",
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
        "((service_name)) has sent ((count_en)) out of its limit of ((message_limit_en)) ((message_type)) per  fiscal year.",
        "((service_name)) has ((remaining)) ((message_type)) remaining until April 1, ((fiscal_end)).",
        "",
        "For more information, visit the usage report for your [service]((hyperlink_to_page_en)).",
        "",
        "The GC Notify Team",
        "",
        "---",
        "",
        "Bonjour ((name)),",
        "",
        "Le service Notification GC comporte des limites annuelles et quotidiennes. Ce message concerne votre limite annuelle.",
        "",
        "((service_name)) a envoyé ((count_en)) ((message type)) et sa limite d’envoi est fixée à ((message_limit_en)) ((message type)) par exercice financier.",
        "((service_name)) peut encore envoyer ((remaining)) ((message type)) d’ici le 1er avril ((fiscal_end)).",
        "",
        "Pour en savoir plus, consultez le rapport d’utilisation pour votre [service]((hyperlink_to_page_fr)).",
        "",
        "L’équipe Notification GC",
        "",
    ]
)

quarterly_annual_limit_email = "\n".join(
    [
        "(la version française suit)",
        "",
        "Hello ((name)),",
        "",
        "We send this report every quarter. You can use it to track the number of messages sent by your services since April 1, ((start_year)).",
        "Review this information so you can plan to stay within the annual sending limits. Limits reset on April 1, ((end_year)).",
        "",
        "((data_for_each_service_en))",
        "" "The GC Notify Team",
        "",
        "---",
        "",
        "" "Bonjour ((name)),",
        "",
        "Nous envoyons ce rapport à chaque trimestre. Vous pouvez l’utiliser pour suivre le nombre de messages envoyés par vos services depuis le 1er avril ((start_year)).",
        "Examinez ces renseignements pour veiller à tenir compte de vos limites d’envoi annuelles. Les limites seront réinitialisées le 1er avril ((end_year)).",
        "",
        "((data_for_each_service_fr))",
        "",
        "L’équipe Notification GC",
        "",
    ]
)


def upgrade():
    template_insert = """
        INSERT INTO templates (id, name, template_type, created_at, content, archived, service_id, subject,
        created_by_id, version, process_type, hidden)
        VALUES ('{}', '{}', '{}', '{}', '{}', False, '{}', '{}', '{}', 1, '{}', false)
    """

    template_history_insert = """
        INSERT INTO templates_history (id, name, template_type, created_at, content, archived, service_id, subject,
        created_by_id, version, process_type, hidden)
        VALUES ('{}', '{}', '{}', '{}', '{}', False, '{}', '{}', '{}', 1, '{}', false)
    """

    templates = [
        {
            "id": near_annual_limit_template_id,
            "name": "Near annual limit",
            "subject": " Alert for ((service_name)) | # Alerte pour ((service_name)).",
            "content": near_annual_limit,
        },
        {
            "id": reached_annual_limit_template_id,
            "name": "Annual limit reached",
            "subject": "Alert for ((service_name)) | # Alerte pour ((service_name))",
            "content": annual_limit_reached,
        },
        {
            "id": annual_limit_updated_template_id,
            "name": "Annual limit updated",
            "subject": "Annual limit update for ((service_name)) | Nous avons mis à jour la limite annuelle pour ((service_name))",
            "content": annual_limit_updated,
        },
        {
            "id": quarterly_annual_limit_template_id,
            "name": "Quarterly annual limit",
            "subject": "Fiscal year April 1,((start_year)) to March 31,((end_year)): your usage to date | Exercice financier allant du 1er avril ((start_year)) au 31 mars ((end_year)) : votre utilisation jusqu’ici",
            "content": quarterly_annual_limit_email,
        },
    ]

    for template in templates:
        op.execute(
            template_insert.format(
                template["id"],
                template["name"],
                "email",
                datetime.utcnow(),
                template["content"],
                current_app.config["NOTIFY_SERVICE_ID"],
                template["subject"],
                current_app.config["NOTIFY_USER_ID"],
                "normal",
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
                "normal",
            )
        )


def downgrade():
    for template_id in template_ids:
        op.execute("DELETE FROM template_redacted WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM templates_history WHERE id = '{}'".format(template_id))
        op.execute("DELETE FROM templates WHERE id = '{}'".format(template_id))
