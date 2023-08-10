import os

SQLALCHEMY_DATABASE_URI = "postgresql://postgres:postgres@localhost:5432/test_notification_api" #os.getenv("SQLALCHEMY_DATABASE_URI")
print(SQLALCHEMY_DATABASE_URI)

import sqlalchemy as sa

# set connection URI here ↓
engine = sa.create_engine(SQLALCHEMY_DATABASE_URI)

with engine.connect() as conn:
    with conn.begin():
        insert_user = """
        INSERT INTO "public"."users"("id","name","email_address","created_at","updated_at","_password","mobile_number","password_changed_at","logged_in_at","failed_login_count","state","platform_admin","current_session_id","auth_type","blocked","additional_information","password_expired")
            VALUES
            (E'3f478896-6d3f-4ef3-aa5a-530fea1206bb',E'Notify UI Tests',E'notify-uid-tests@cds-snc.ca',E'2023-05-24 13:41:48.022737',E'2023-08-01 13:20:08.017647',E'$2b$10$jwj45gXRLUIteNBwhRgEV.4P7uHGH11O2PhNiDK6SY6oRPSdKhg2u',E'6139863526',E'2023-05-24 13:41:48.017676',E'2023-08-01 13:20:08.014524',0,E'active',FALSE,E'8f6e79df-782d-4620-b86c-adf1ea933934',E'email_auth',FALSE,E'{}',FALSE);
        """
        
        insert_service = """
            INSERT INTO "public"."services"("id","name","created_at","updated_at","active","message_limit","restricted","email_from","created_by_id","version","research_mode","organisation_type","prefix_sms","crown","rate_limit","contact_link","consent_to_research","volume_email","volume_letter","volume_sms","count_as_live","go_live_at","go_live_user_id","organisation_id","sending_domain","default_branding_is_french","sms_daily_limit","organisation_notes")
            VALUES
            (E'4049c2d0-0cab-455c-8f4c-f356dff51810',E'Cypress',E'2023-05-16 15:02:43.663183',E'2023-05-24 14:01:51.335072',TRUE,10000,FALSE,E'bounce',E'6af522d0-2915-4e52-83a3-3690455a5fe6',5,FALSE,E'central',TRUE,TRUE,1000,NULL,NULL,NULL,NULL,NULL,FALSE,E'2023-05-16 15:08:46.692247',NULL,E'93413f91-227f-4704-b229-b8210d1ecc0a',NULL,FALSE,1000,NULL);
        """
        
        insert_templates = """
            INSERT INTO "public"."templates"("id","name","template_type","created_at","updated_at","content","service_id","subject","created_by_id","version","archived","process_type","service_letter_contact_id","hidden","postage")
            VALUES
            (E'136e951e-05c8-4db4-bc50-fe122d72fcaa',E'SMOKE_TEST_EMAIL',E'email',E'2023-05-24 13:31:40.907915',NULL,E'# This is a smoke test from Cypress\n\nSMOKE_TEST_EMAIL',E'4049c2d0-0cab-455c-8f4c-f356dff51810',E'SMOKE_TEST_EMAIL',E'0840b12a-8139-4627-b27a-58872913ae14',1,FALSE,E'bulk',NULL,FALSE,NULL),
            (E'258d8617-da88-4faa-ad28-46cc69f5a458',E'VARIABLES_EMAIL_TEMPLATE_ID',E'email',E'2023-07-10 16:38:43.913184',NULL,E'Hi ((name))\n\n((has_stuff??You have stuff!))',E'4049c2d0-0cab-455c-8f4c-f356dff51810',E'TESTING',E'0840b12a-8139-4627-b27a-58872913ae14',1,FALSE,E'bulk',NULL,FALSE,NULL),
            (E'2d52d997-42d3-4ac0-a597-7afc94d4339a',E'SMOKE_TEST_EMAIL_LINK',E'email',E'2023-05-24 13:32:49.286647',NULL,E'# This is a smoke test from Cypress\n\nSMOKE_TEST_EMAIL_LINK\n\n((link_to_file))',E'4049c2d0-0cab-455c-8f4c-f356dff51810',E'SMOKE_TEST_EMAIL_LINK',E'0840b12a-8139-4627-b27a-58872913ae14',1,FALSE,E'bulk',NULL,FALSE,NULL),
            (E'48207d93-144d-4ebb-92c5-99ff1f1baead',E'SMOKE_TEST_EMAIL_BULK',E'email',E'2023-05-24 13:32:24.912515',NULL,E'# This is a smoke test from Cypress\n\nSMOKE_TEST_EMAIL_BULK',E'4049c2d0-0cab-455c-8f4c-f356dff51810',E'SMOKE_TEST_EMAIL_BULK',E'0840b12a-8139-4627-b27a-58872913ae14',1,FALSE,E'bulk',NULL,FALSE,NULL),
            (E'58db03d6-a9d8-4482-8621-26f473f3980a',E'SMOKE_TEST_EMAIL_ATTACH',E'email',E'2023-05-24 13:32:03.754124',NULL,E'# This is a smoke test from Cypress\n\nSMOKE_TEST_EMAIL_ATTACH',E'4049c2d0-0cab-455c-8f4c-f356dff51810',E'SMOKE_TEST_EMAIL_ATTACH',E'0840b12a-8139-4627-b27a-58872913ae14',1,FALSE,E'bulk',NULL,FALSE,NULL),
            (E'5945e2f0-3e37-4813-9a60-e0665e02e9c8',E'SMOKE_TEST_SMS',E'sms',E'2023-05-24 13:33:20.936811',NULL,E'SMOKE_TEST_SMS',E'4049c2d0-0cab-455c-8f4c-f356dff51810',NULL,E'0840b12a-8139-4627-b27a-58872913ae14',1,FALSE,E'bulk',NULL,FALSE,NULL),
            (E'b4692883-4182-4a23-b1b9-7b9df66a66e8',E'SIMPLE_EMAIL_TEMPLATE_ID',E'email',E'2023-07-10 16:33:10.288618',NULL,E'TESTING',E'4049c2d0-0cab-455c-8f4c-f356dff51810',E'TESTING',E'0840b12a-8139-4627-b27a-58872913ae14',1,FALSE,E'bulk',NULL,FALSE,NULL);
        """
        
        insert_api_keys = """
            INSERT INTO "public"."api_keys"("id","name","secret","service_id","expiry_date","created_at","created_by_id","updated_at","version","key_type")
            VALUES
            (E'076fc5ba-8578-44d6-8b69-122ac3a7b206',E'CYPRESS_TEST_KEY',E'IjY3YTViZmU4LWMxNjktNDQ0NS04OGVjLWRkNWExZDA3NjFmYSI.wLt-AQOYG3vgab_qP1p0Djw_r-8',E'4049c2d0-0cab-455c-8f4c-f356dff51810',NULL,E'2023-07-10 16:44:13.025984',E'6af522d0-2915-4e52-83a3-3690455a5fe6',NULL,1,E'test'),
            (E'61a3f8e1-516d-446c-bc3a-c2dac33c9474',E'CYPRESS',E'IjhmYmE3MzUwLTIwN2ItNDRhYi1iNmYwLTVkZjk3ZjAzNjZlMyI.xiQ94d2oAedkohXNhx83B6cWr_0',E'4049c2d0-0cab-455c-8f4c-f356dff51810',NULL,E'2023-05-24 13:48:23.93561',E'6af522d0-2915-4e52-83a3-3690455a5fe6',NULL,1,E'normal'),
            (E'74a06881-7742-4d4a-85ff-b91ae71e1bcd',E'CYPRESS_TEAM_KEY',E'IjYxZjhhYzU3LTNlZGEtNDE3MS1iMDcyLTJjNTY0OWEzODI4ZSI.p6K5JNnYp6Pcn3OEQg1kDM1UHAY',E'4049c2d0-0cab-455c-8f4c-f356dff51810',NULL,E'2023-07-10 16:43:19.425995',E'6af522d0-2915-4e52-83a3-3690455a5fe6',NULL,1,E'team');
        """# Optional: start a transaction
        # conn.execute(sa.text(insert_user))
        conn.execute(sa.text(insert_service))
        conn.execute(sa.text(insert_templates))
        conn.execute(sa.text(insert_api_keys))
