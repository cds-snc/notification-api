"""

Revision ID: 0497_newsletter_service
Revises: 0496_newsletter_templates
Create Date: 2025-11-24 00:00:00

"""
from datetime import datetime

from alembic import op
from flask import current_app


revision = "0497_newsletter_service"
down_revision = "0496_newsletter_templates"

# Get the admin base URL from config for environment-specific links
admin_base_url = current_app.config.get("ADMIN_BASE_URL", "http://localhost:6012")

newsletter_confirmation_template_en_id = current_app.config["NEWSLETTER_CONFIRMATION_EMAIL_TEMPLATE_ID_EN"]
newsletter_confirmation_template_fr_id = current_app.config["NEWSLETTER_CONFIRMATION_EMAIL_TEMPLATE_ID_FR"]
confirmation_templates = [newsletter_confirmation_template_en_id, newsletter_confirmation_template_fr_id]

# Base newsletter templates from 0496
newsletter_template_id = current_app.config["NEWSLETTER_SAMPLE_FOOTER_EMAIL_TEMPLATE_ID"]
old_base_templates = ["c3a0273c-ea55-4de4-a688-018ab909795d", "0422ee2d-0e13-4d6b-a52c-77e59e7dd89c"]

newsletter_service_id = current_app.config["NEWSLETTER_SERVICE_ID"]
user_id = current_app.config["NOTIFY_USER_ID"]

notify_service_id = current_app.config["NOTIFY_SERVICE_ID"]
CAT_CONFIRM_ID = "977e2a00-f957-4ff0-92f2-ca3286b24786"
CAT_TEST_ID = "7c16aa95-e2e1-4497-81d6-04c656520fe4"

# SQL templates
template_update = """
    UPDATE templates SET content = '{}', version = '{}', updated_at = '{}', template_category_id = '{}'
    WHERE id = '{}'
"""
template_insert = """
    INSERT INTO templates (id, name, template_type, created_at, content, archived, service_id, subject,
    created_by_id, version, hidden)
    VALUES ('{}', '{}', '{}', '{}', '{}', False, '{}', '{}', '{}', '{}', false)
"""
template_history_insert = """
    INSERT INTO templates_history (id, name, template_type, created_at, content, archived, service_id, subject,
    created_by_id, version, template_category_id, hidden)
    VALUES ('{}', '{}', '{}', '{}', '{}', False, '{}', '{}', '{}', '{}', '{}', false)
"""

def upgrade():
    # Set up newsletter service and user
    service_history_insert = f"""INSERT INTO services_history (id, name, created_at, active, message_limit, restricted, research_mode, email_from, created_by_id, organisation_id, sms_daily_limit, prefix_sms, organisation_type, version)
                    VALUES ('{newsletter_service_id}', 'Notify Newsletter', '{datetime.utcnow()}', True, 20000, False, False, 'newsletter',
                    '{user_id}', (SELECT organisation_id FROM services WHERE id = '{notify_service_id}'), 0, False, 'central', 1)
                """
    op.execute(service_history_insert)
    
    service_insert = f"""INSERT INTO services (id, name, created_at, active, message_limit, restricted, research_mode, email_from, created_by_id, organisation_id, sms_daily_limit, prefix_sms, organisation_type, version)
                        VALUES ('{newsletter_service_id}', 'Notify Newsletter', '{datetime.utcnow()}', True, 20000, False, False, 'newsletter',
                        '{user_id}', (SELECT organisation_id FROM services WHERE id = '{notify_service_id}'), 0, False, 'central', 1)
                    """
    op.execute(service_insert)

    # Notify user <-> Newsletter service
    user_to_service_insert = f"""INSERT INTO user_to_service (user_id, service_id) VALUES ('{user_id}', '{newsletter_service_id}')"""
    op.execute(user_to_service_insert)
    
    # Service permissions
    service_permissions_insert = f"""INSERT INTO service_permissions (service_id, permission, created_at) VALUES ('{newsletter_service_id}', 'email', '{datetime.utcnow()}')"""
    op.execute(service_permissions_insert)

    # Remove old base newsletter templates
    for template_id in old_base_templates:
        op.execute("DELETE FROM notifications WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM notification_history WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM template_redacted WHERE template_id = '{}'".format(template_id))
        op.execute("DELETE FROM templates_history WHERE id = '{}'".format(template_id))
        op.execute("DELETE FROM templates WHERE id = '{}'".format(template_id))


    # Reference template with footer content
    sample_footers_content = "\n".join(
        [
            f"[Unsubscribe]({admin_base_url}/newsletter/((subscriber_id))/unsubscribe) / [Change language]({admin_base_url}/newsletter/((subscriber_id))/change-language)",
            "",
            f"[Se désabonner]({admin_base_url}/newsletter/((subscriber_id))/unsubscribe?lang=fr) / [Changer la langue]({admin_base_url}/newsletter/((subscriber_id))/change-language?lang=fr)"
        ]
    )

    newsletter_footer_template = {
        "id": newsletter_template_id,
        "name": "REFERENCE - Newsletter footers",
        "subject": "Reference use only, no sending going on here",
        "content": sample_footers_content,
        "template_type": "email",  
        "template_category_id": CAT_TEST_ID,
    }

    # Test template category id for footer templates
    footer_template_insert = """
        INSERT INTO templates (id, name, template_type, created_at, content, archived, service_id, subject,
        created_by_id, version, template_category_id, hidden)
        VALUES ('{}', '{}', '{}', '{}', '{}', False, '{}', '{}', '{}', 1, '{}', false)
    """

    # Insert footer reference template
    op.execute(
        footer_template_insert.format(
            newsletter_footer_template["id"],
            newsletter_footer_template["name"],
            newsletter_footer_template["template_type"],
            datetime.utcnow(),
            newsletter_footer_template["content"],
            current_app.config["NEWSLETTER_SERVICE_ID"],
            newsletter_footer_template["subject"],
            current_app.config["NOTIFY_USER_ID"],
            newsletter_footer_template["template_category_id"],
        )
    )

    op.execute(
        template_history_insert.format(
            newsletter_footer_template["id"],
            newsletter_footer_template["name"],
            newsletter_footer_template["template_type"],
            datetime.utcnow(),
            newsletter_footer_template["content"],
            current_app.config["NEWSLETTER_SERVICE_ID"],
            newsletter_footer_template["subject"],
            current_app.config["NOTIFY_USER_ID"],
            1,
            newsletter_footer_template["template_category_id"],
        )
    )

    # Update confirmation email content
    template_content_en = "\n".join(
        [
            "To confirm your subscription, select the following link:",
            "",
            "((confirmation_link))",
            "",
            "We use a third-party application called Airtable to collect email addresses. For more information, read [Airtable’s privacy policy](https://www.airtable.com/company/privacy).",
            "",
            "To learn how GC Notify protects your privacy, read our [Privacy Statement](https://notification.canada.ca/privacy). ",
            "",
            "The GC Notify Team"
        ]
    )
    
    template_content_fr = "\n".join(
        [
            "Pour confirmer votre abonnement, suivez ce lien :",
            "",
            "((confirmation_link))?lang=fr",
            "",
            "Nous employons un service tiers nommé Airtable pour collecter les adresses courriel. Pour plus de renseignements, consultez [l’avis de confidentialité de Airtable](https://www.airtable.com/company/privacy/fr).",
            "",
            "Pour en savoir plus sur la façon dont Notification GC assure la confidentialité de vos données, consultez notre [avis de confidentialité](https://notification.canada.ca/confidentialite).",
            "",
            "L’équipe Notification GC"
        ]
    )

    confirm_templates = [
        {
            "id": newsletter_confirmation_template_en_id,
            "name": "EN Newsletter subscription confirmation",
            "subject": "Welcome to the GC Notify newsletter",
            "content": template_content_en,
            "template_type": "email",  
            "category_id": CAT_CONFIRM_ID,
        },
        {
            "id": newsletter_confirmation_template_fr_id,
            "name": "FR Newsletter subscription confirmation",
            "subject": "Bienvenue à l’infolettre de Notification GC",
            "content": template_content_fr,
            "template_type": "email",  
            "category_id": CAT_CONFIRM_ID,
        },
    ]



    conn = op.get_bind()
    for template in confirm_templates:
        current_version = conn.execute("select version from templates where id='{}'".format(template["id"])).fetchone()
        template["version"] = current_version[0] + 1
        
        op.execute(
            template_update.format(
                template["content"],
                template["version"],
                datetime.utcnow(),
                template["category_id"],
                template["id"]
            )
        )

        op.execute(
            template_history_insert.format(
                template["id"],
                template["name"],
                template["template_type"],
                datetime.utcnow(),
                template["content"],
                current_app.config["NOTIFY_SERVICE_ID"],
                template["subject"],
                current_app.config["NOTIFY_USER_ID"],
                template["version"],
                template["category_id"],
            )
        )


def downgrade():
    # Restore confirmation templates to their original state (without category and with original content from 0495)
    template_content_en_original = "\n".join(
        [
            "To confirm your subscription, select the following link:",
            "",
            "((confirmation_link))",
            "",
            "We use a third-party application called Airtable to collect email addresses. For more information, read [Airtable’s privacy policy](https://www.airtable.com/company/privacy).",
            "",
            "To learn how GC Notify protects your privacy, read our [Privacy Statement](https://notification.canada.ca/privacy). ",
            "",
            "The GC Notify Team"
        ]
    )
    
    template_content_fr_original = "\n".join(
        [
            "Pour confirmer votre abonnement, suivez ce lien :",
            "",
            "((confirmation_link))",
            "",
            "Nous employons un service tiers nommé Airtable pour collecter les adresses courriel. Pour plus de renseignements, consultez [l’avis de confidentialité de Airtable](https://www.airtable.com/company/privacy/fr).",
            "",
            "Pour en savoir plus sur la façon dont Notification GC assure la confidentialité de vos données, consultez notre [avis de confidentialité](https://notification.canada.ca/confidentialite).",
            "",
            "L’équipe Notification GC"
        ]
    )
    
    restore_templates = [
        {
            "id": newsletter_confirmation_template_en_id,
            "name": "EN Newsletter subscription confirmation",
            "subject": "Welcome to the GC Notify newsletter",
            "content": template_content_en_original,
        },
        {
            "id": newsletter_confirmation_template_fr_id,
            "name": "FR Newsletter subscription confirmation",
            "subject": "Bienvenue à l’infolettre de Notification GC",
            "content": template_content_fr_original,
        },
    ]
    
    conn = op.get_bind()
    for template in restore_templates:
        current_version = conn.execute(f"select version from templates where id='{template['id']}'").fetchone()
        template["version"] = current_version[0] + 1
        
        # Update template back to original content and remove category
        op.execute(f"""
            UPDATE templates SET content = '{template["content"]}', version = {template["version"]}, 
            updated_at = '{datetime.utcnow()}', template_category_id = NULL
            WHERE id = '{template["id"]}'
        """)
        
        # Add history entry
        op.execute(f"""
            INSERT INTO templates_history (id, name, template_type, created_at, content, archived, service_id, subject,
            created_by_id, version, template_category_id, hidden)
            VALUES ('{template["id"]}', '{template["name"]}', 'email', '{datetime.utcnow()}', 
            '{template["content"]}', False, '{current_app.config["NOTIFY_SERVICE_ID"]}', '{template["subject"]}', 
            '{current_app.config["NOTIFY_USER_ID"]}', {template["version"]}, NULL, false)
        """)
    
    # Remove reference footer template
    op.execute(f"DELETE FROM notifications WHERE template_id = '{newsletter_template_id}'")
    op.execute(f"DELETE FROM notification_history WHERE template_id = '{newsletter_template_id}'")
    op.execute(f"DELETE FROM template_redacted WHERE template_id = '{newsletter_template_id}'")
    op.execute(f"DELETE FROM templates_history WHERE id = '{newsletter_template_id}'")
    op.execute(f"DELETE FROM templates WHERE id = '{newsletter_template_id}'")
    
    # Remove service permissions
    op.execute(f"DELETE FROM service_permissions WHERE service_id = '{newsletter_service_id}'")
    
    # Remove user to service mapping
    op.execute(f"DELETE FROM user_to_service WHERE user_id = '{user_id}' AND service_id = '{newsletter_service_id}'")
    
    # Remove service
    op.execute(f"DELETE FROM services WHERE id = '{newsletter_service_id}'")
    op.execute(f"DELETE FROM services_history WHERE id = '{newsletter_service_id}'")
