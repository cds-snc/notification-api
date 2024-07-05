"""

Revision ID: 0455_add_starter_category
Revises: 0454_add_template_category
Create Date: 2024-06-11 13:32:00
"""
from alembic import op

revision = "0455_add_starter_category"
down_revision = "0454_add_template_category"

CAT_ALERT_ID = "1d8ce435-a7e5-431b-aaa2-a418bc4d14f9"
CAT_AUTH_ID = "b6c42a7e-2a26-4a07-802b-123a5c3198a9"
CAT_AUTO_ID = "977e2a00-f957-4ff0-92f2-ca3286b24786"
CAT_DECISION_ID = "e81678c0-4897-4111-b9d0-172f6b595f89"
CAT_INFO_ID = "207b293c-2ae5-48e8-836d-fcabd60b2153"
CAT_REMINDER_ID = "edb966f3-4a4c-47a4-96ab-05ff259b919c"
CAT_REQUEST_ID = "e0b8fbe5-f435-4977-8fc8-03f13d9296a5"
CAT_STATUS_ID = "55eb1137-6dc6-4094-9031-f61124a279dc"
CAT_TEST_ID = "7c16aa95-e2e1-4497-81d6-04c656520fe4"

# List of category IDs
category_ids = [
    CAT_ALERT_ID,
    CAT_AUTH_ID,
    CAT_AUTO_ID,
    CAT_DECISION_ID,
    CAT_INFO_ID,
    CAT_REMINDER_ID,
    CAT_REQUEST_ID,
    CAT_STATUS_ID,
    CAT_TEST_ID,
]

# Corresponding English and French names and descriptions and process_type
category_data = [
    ("Alert", "Alerte", "System checks and monitoring", "Contrôles et surveillance du système", "medium", "medium"),
    (
        "Authentication",
        "Authentification",
        "Password resets and two factor verification",
        "Réinitialisations de mot de passe et vérification à deux facteurs",
        "priority",
        "priority",
    ),
    (
        "Automatic reply",
        "Réponse automatique",
        "No-reply and confirmation messages",
        "Messages automatiques de non-réponse et de confirmation",
        "priority",
        "priority",
    ),
    ("Decision", "Décision", "Permits, documents and results", "Livraisons de permis, documents et résultats", "low", "low"),
    (
        "Information blast",
        "Diffusion d'informations",
        "Newsletters, surveys and general information",
        "Bulletins d'information, enquêtes et informations générales",
        "bulk",
        "bulk",
    ),
    ("Reminder", "Rappel", "Appointments and deadlines", "Rendez-vous et échéances", "normal", "normal"),
    ("Request", "Demande", "Request: Follow up and next steps", "Suivis et prochaines étapes", "normal", "normal"),
    ("Status update", "Mise à jour du statut", "Changes and progress", "Changements et progrès", "normal", "normal"),
    ("Test", "Test", "Practice messages", "Messages de pratique", "bulk", "bulk"),
]


def upgrade():
    # Insert new process_type
    op.execute("INSERT INTO template_process_type (name) VALUES ('low')")
    op.execute("INSERT INTO template_process_type (name) VALUES ('medium')")
    op.execute("INSERT INTO template_process_type (name) VALUES ('high')")

    def insert_statement(id, name_en, name_fr, description_en, description_fr, sms_process_type, email_process_type):
        # Escape single quotes in string values
        name_fr = name_fr.replace("'", "''")
        description_fr = description_fr.replace("'", "''")

        return f"""
        INSERT INTO template_categories 
        (id, name_en, name_fr, description_en, description_fr, sms_process_type, email_process_type, hidden, created_at)
        VALUES 
        ('{id}', '{name_en}', '{name_fr}', '{description_en}', '{description_fr}', '{sms_process_type}', '{email_process_type}', false, now())
        """

    for id, (name_en, name_fr, desc_en, desc_fr, sms_process_type, email_process_type) in zip(category_ids, category_data):
        stmt = insert_statement(id, name_en, name_fr, desc_en, desc_fr, sms_process_type, email_process_type)
        op.execute(stmt)


def downgrade():
    for id in category_ids:
        op.execute(f"DELETE FROM template_categories WHERE id = '{id}'")

    # Delete process_type
    op.execute("DELETE FROM template_process_type WHERE name = 'low'")
    op.execute("DELETE FROM template_process_type WHERE name = 'medium'")
    op.execute("DELETE FROM template_process_type WHERE name = 'high'")
