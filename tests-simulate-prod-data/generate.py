"""
test-simulate-prod-data: Generate non-PII production-like data in a staging database.

Usage:
    python generate.py               # populate data
    python generate.py --cleanup-only  # remove all test-simulate-prod-data entities

Requires SQLALCHEMY_DATABASE_URI env var (or .env file).
"""

import io
import math
import random
import uuid
from datetime import datetime, timedelta, timezone

import click
from dateutil import rrule
from sim_config import PREFIX, Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


def _timestamp():
    """Return current timestamp for logging."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FAKE_EMAIL_DOMAIN = "staging-simulate.local"
FAKE_PHONE = "+16135550199"

VARIABLE_NAMES = [
    "first_name",
    "last_name",
    "reference_number",
    "date",
    "amount",
    "service_name",
    "address",
    "account_id",
    "status",
    "link",
    "confirmation_code",
    "expiry_date",
    "case_number",
    "department",
    "action_required",
]

EMAIL_PROVIDERS = ["ses"]
SMS_PROVIDERS = ["sns"]

NOTIFICATION_TYPE_EMAIL = "email"
NOTIFICATION_TYPE_SMS = "sms"


def _uuid():
    return uuid.uuid4()


def _random_date(start_date, end_date):
    """Return a random datetime between start_date and end_date."""
    delta = end_date - start_date
    random_days = random.randint(0, delta.days)
    random_seconds = random.randint(0, 86399)
    return datetime.combine(start_date, datetime.min.time()) + timedelta(days=random_days, seconds=random_seconds)


def _template_content(num_vars, template_type):
    """Generate template content with {{placeholder}} variables."""
    chosen = random.sample(VARIABLE_NAMES, min(num_vars, len(VARIABLE_NAMES)))
    if template_type == NOTIFICATION_TYPE_EMAIL:
        lines = [f"Dear {{{{{chosen[0]}}}}}," if chosen else "Dear user,"]
        lines.append("")
        lines.append("This is a notification regarding your account.")
        for var in chosen[1:]:
            lines.append(f"Your {var.replace('_', ' ')}: {{{{{var}}}}}")
        lines.append("")
        lines.append("Thank you.")
        return "\n".join(lines)
    else:
        parts = [f"{{{{{v}}}}}" for v in chosen]
        return f"Notification: {' | '.join(parts)}"


def _template_subject(num_vars, chosen_vars):
    """Generate an email subject with a variable."""
    if chosen_vars:
        return f"Notification for {{{{{chosen_vars[0]}}}}}"
    return "Notification"


# ---------------------------------------------------------------------------
# Database setup using raw SQLAlchemy (no Flask app context needed)
# ---------------------------------------------------------------------------


def get_engine():
    Config.validate()
    return create_engine(
        Config.SQLALCHEMY_DATABASE_URI,
        echo=False,
    )


def _copy_rows(session, table_name, columns, rows):
    """Use PostgreSQL COPY FROM STDIN for fastest possible bulk insert.

    COPY bypasses the SQL parser and streams data directly into the table,
    making it 5-10x faster than even multi-row INSERT VALUES.
    """
    if not rows:
        return

    buf = io.StringIO()
    for row in rows:
        values = []
        for col in columns:
            val = row[col]
            if val is None:
                values.append("\\N")
            elif isinstance(val, bool):
                values.append("t" if val else "f")
            elif isinstance(val, datetime):
                values.append(val.isoformat())
            else:
                values.append(str(val))
        buf.write("\t".join(values) + "\n")

    buf.seek(0)

    col_list = ", ".join(f'"{c}"' for c in columns)
    copy_sql = f"COPY {table_name} ({col_list}) FROM STDIN"

    raw_conn = session.connection().connection
    cursor = raw_conn.cursor()
    cursor.copy_expert(copy_sql, buf)
    cursor.close()


# ---------------------------------------------------------------------------
# Data generation functions
# ---------------------------------------------------------------------------


def create_organisation(session):
    org_id = _uuid()
    print(f"  Creating organisation '{Config.ORGANISATION_NAME}' ({org_id})...")
    session.execute(
        text("""
        INSERT INTO organisation (id, name, active, created_at, default_branding_is_french, organisation_type)
        VALUES (:id, :name, true, :now, false, 'central')
    """),
        {"id": str(org_id), "name": Config.ORGANISATION_NAME, "now": datetime.now(timezone.utc)},
    )
    return org_id


def create_users(session):
    users = []
    for i in range(1, Config.NUM_USERS + 1):
        user_id = _uuid()
        email = f"{PREFIX}-user-{i}@{FAKE_EMAIL_DOMAIN}"
        print(f"  Creating user {i}/{Config.NUM_USERS}: {email} ({user_id})...")
        session.execute(
            text("""
            INSERT INTO users (id, name, email_address, _password, mobile_number,
                               password_changed_at, state, auth_type, created_at, blocked,
                               platform_admin, failed_login_count, password_expired)
            VALUES (:id, :name, :email, :password, :mobile,
                    :now, 'active', 'email_auth', :now, true,
                    false, 0, false)
        """),
            {
                "id": str(user_id),
                "name": f"{PREFIX} User {i}",
                "email": email,
                "password": "simulated-no-login",  # not a real bcrypt hash — these users should never log in
                "mobile": FAKE_PHONE,
                "now": datetime.now(timezone.utc),
            },
        )
        users.append({"id": user_id, "email": email, "index": i})
    return users


def create_service(session, users, org_id):
    service_id = _uuid()
    creator = users[0]
    print(f"  Creating service '{Config.SERVICE_NAME}' ({service_id})...")
    session.execute(
        text("""
        INSERT INTO services (id, name, created_by_id, created_at, active, restricted,
                              message_limit, sms_daily_limit, sms_annual_limit, email_annual_limit,
                              email_from, organisation_type, prefix_sms, rate_limit,
                              count_as_live, research_mode, organisation_id, version,
                              default_branding_is_french)
        VALUES (:id, :name, :created_by, :now, true, false,
                :message_limit, :sms_daily_limit, :sms_annual_limit, :email_annual_limit,
                :email_from, 'central', true, :rate_limit,
                true, false, :org_id, 1, false)
    """),
        {
            "id": str(service_id),
            "name": Config.SERVICE_NAME,
            "created_by": str(creator["id"]),
            "now": datetime.now(timezone.utc),
            "message_limit": Config.SERVICE_MESSAGE_LIMIT,
            "sms_daily_limit": Config.SERVICE_SMS_DAILY_LIMIT,
            "sms_annual_limit": Config.SERVICE_SMS_ANNUAL_LIMIT,
            "email_annual_limit": Config.SERVICE_EMAIL_ANNUAL_LIMIT,
            "email_from": Config.SERVICE_EMAIL_FROM,
            "rate_limit": Config.SERVICE_RATE_LIMIT,
            "org_id": str(org_id),
        },
    )

    # Also insert into services_history (Versioned pattern)
    session.execute(
        text("""
        INSERT INTO services_history (id, name, created_by_id, created_at, active, restricted,
                              message_limit, sms_daily_limit, sms_annual_limit, email_annual_limit,
                              email_from, organisation_type, prefix_sms, rate_limit,
                              count_as_live, research_mode, organisation_id, version,
                              default_branding_is_french)
        VALUES (:id, :name, :created_by, :now, true, false,
                :message_limit, :sms_daily_limit, :sms_annual_limit, :email_annual_limit,
                :email_from, 'central', true, :rate_limit,
                true, false, :org_id, 1, false)
    """),
        {
            "id": str(service_id),
            "name": Config.SERVICE_NAME,
            "created_by": str(creator["id"]),
            "now": datetime.now(timezone.utc),
            "message_limit": Config.SERVICE_MESSAGE_LIMIT,
            "sms_daily_limit": Config.SERVICE_SMS_DAILY_LIMIT,
            "sms_annual_limit": Config.SERVICE_SMS_ANNUAL_LIMIT,
            "email_annual_limit": Config.SERVICE_EMAIL_ANNUAL_LIMIT,
            "email_from": Config.SERVICE_EMAIL_FROM,
            "rate_limit": Config.SERVICE_RATE_LIMIT,
            "org_id": str(org_id),
        },
    )
    return service_id


def link_users_to_service(session, users, service_id):
    print(f"  Linking {len(users)} users to service...")
    for u in users:
        session.execute(
            text("""
            INSERT INTO user_to_service (user_id, service_id)
            VALUES (:uid, :sid)
        """),
            {"uid": str(u["id"]), "sid": str(service_id)},
        )


def grant_user_permissions(session, users, service_id):
    permissions = [
        "manage_users",
        "manage_templates",
        "manage_settings",
        "send_texts",
        "send_emails",
        "send_letters",
        "manage_api_keys",
        "view_activity",
    ]
    print(f"  Granting permissions to {len(users)} users...")
    for u in users:
        for perm in permissions:
            session.execute(
                text("""
                INSERT INTO permissions (id, service_id, user_id, permission, created_at)
                VALUES (:id, :sid, :uid, :perm, :now)
            """),
                {
                    "id": str(_uuid()),
                    "sid": str(service_id),
                    "uid": str(u["id"]),
                    "perm": perm,
                    "now": datetime.now(timezone.utc),
                },
            )


def grant_service_permissions(session, service_id):
    svc_permissions = ["email", "sms", "international_sms", "schedule_notifications"]
    print(f"  Granting service permissions: {svc_permissions}...")
    for perm in svc_permissions:
        session.execute(
            text("""
            INSERT INTO service_permissions (service_id, permission, created_at)
            VALUES (:sid, :perm, :now)
        """),
            {"sid": str(service_id), "perm": perm, "now": datetime.now(timezone.utc)},
        )


def grant_folder_permissions(session, users, service_id, folder_ids):
    """Grant all users access to all template folders."""
    print(f"  Granting folder permissions to {len(users)} users for {len(folder_ids)} folders...")
    for u in users:
        for fid in folder_ids:
            session.execute(
                text("""
                INSERT INTO user_folder_permissions (user_id, template_folder_id, service_id)
                VALUES (:uid, :fid, :sid)
            """),
                {"uid": str(u["id"]), "fid": str(fid), "sid": str(service_id)},
            )


def create_api_key(session, service_id, creator_id):
    """Skip API key creation — the secret column requires app-level signing (SECRET_KEY).

    Inserting a raw UUID would produce a record that can never authenticate and
    would cause BadSignature errors if the app ever reads it.  Jobs and
    notification_history allow NULL api_key_id, so we simply omit the record.
    """
    print("  Skipping API key creation (secret requires app signing config).")
    return None


def create_reply_to(session, service_id):
    reply_id = _uuid()
    print(f"  Creating reply-to address ({reply_id})...")
    session.execute(
        text("""
        INSERT INTO service_email_reply_to (id, service_id, email_address, is_default, archived, created_at)
        VALUES (:id, :sid, :email, true, false, :now)
    """),
        {
            "id": str(reply_id),
            "sid": str(service_id),
            "email": f"reply-{PREFIX}@{FAKE_EMAIL_DOMAIN}",
            "now": datetime.now(timezone.utc),
        },
    )
    return reply_id


def create_callback(session, service_id, creator_id):
    """Skip callback creation — bearer_token requires app-level signing (SECRET_KEY)."""
    print("  Skipping service callback (bearer_token requires app signing config).")
    return None


def create_annual_billing(session, service_id):
    """Create annual_billing record for the current fiscal year."""
    # Canadian fiscal year starts April 1
    now = datetime.now(timezone.utc)
    fiscal_year_start = now.year if now.month >= 4 else now.year - 1
    billing_id = _uuid()
    print(f"  Creating annual_billing for fiscal year {fiscal_year_start} ({billing_id})...")
    session.execute(
        text("""
        INSERT INTO annual_billing (id, service_id, financial_year_start, free_sms_fragment_limit, created_at)
        VALUES (:id, :sid, :year, :limit, :now)
    """),
        {
            "id": str(billing_id),
            "sid": str(service_id),
            "year": fiscal_year_start,
            "limit": Config.SERVICE_SMS_ANNUAL_LIMIT,
            "now": datetime.now(timezone.utc),
        },
    )
    return billing_id


def create_sms_sender(session, service_id):
    """Create a default SMS sender for the service."""
    sender_id = _uuid()
    print(f"  Creating default SMS sender ({sender_id})...")
    session.execute(
        text("""
        INSERT INTO service_sms_senders (id, sms_sender, service_id, is_default, created_at)
        VALUES (:id, :sender, :sid, true, :now)
    """),
        {
            "id": str(sender_id),
            "sid": str(service_id),
            "sender": "NOTIFY",
            "now": datetime.now(timezone.utc),
        },
    )
    return sender_id


def link_existing_user(session, service_id, folder_ids):
    """Link an existing real user to the service so they can access it from the frontend."""
    email = Config.LINK_EXISTING_USER_EMAIL
    if not email:
        return

    result = session.execute(text("SELECT id FROM users WHERE email_address = :email"), {"email": email})
    row = result.fetchone()
    if not row:
        print(f"  WARNING: User '{email}' not found in database — skipping link.")
        return

    user_id = str(row[0])
    print(f"  Linking existing user '{email}' ({user_id}) to service...")

    # user_to_service
    session.execute(
        text("INSERT INTO user_to_service (user_id, service_id) VALUES (:uid, :sid)"),
        {"uid": user_id, "sid": str(service_id)},
    )

    # Grant permissions
    permissions = [
        "manage_users",
        "manage_templates",
        "manage_settings",
        "send_texts",
        "send_emails",
        "send_letters",
        "manage_api_keys",
        "view_activity",
    ]
    for perm in permissions:
        session.execute(
            text("""
            INSERT INTO permissions (id, service_id, user_id, permission, created_at)
            VALUES (:id, :sid, :uid, :perm, :now)
        """),
            {
                "id": str(_uuid()),
                "sid": str(service_id),
                "uid": user_id,
                "perm": perm,
                "now": datetime.now(timezone.utc),
            },
        )

    # Grant folder permissions
    for fid in folder_ids:
        session.execute(
            text("""
            INSERT INTO user_folder_permissions (user_id, template_folder_id, service_id)
            VALUES (:uid, :fid, :sid)
        """),
            {"uid": user_id, "fid": str(fid), "sid": str(service_id)},
        )


def create_template_folders(session, service_id):
    folder_ids = []
    folder_names = []
    for i in range(1, Config.NUM_TEMPLATE_FOLDERS + 1):
        fid = _uuid()
        name = f"{PREFIX}-folder-{i}" if i > 1 else f"{PREFIX}-folder-high-volume"
        print(f"  Creating template folder '{name}' ({fid})...")
        session.execute(
            text("""
            INSERT INTO template_folder (id, service_id, name)
            VALUES (:id, :sid, :name)
        """),
            {"id": str(fid), "sid": str(service_id), "name": name},
        )
        folder_ids.append(fid)
        folder_names.append(name)
    return folder_ids, folder_names


def create_templates(session, service_id, creator_id, folder_ids):
    """Create templates across folders. Folder 0 (high-volume) gets the bulk."""
    all_template_ids = []
    email_template_ids = []
    sms_template_ids = []

    # Folder 0: high-volume folder
    hv_count = Config.HIGH_VOLUME_FOLDER_TEMPLATE_COUNT
    print(f"  Creating {hv_count} templates in high-volume folder...")
    for i in range(hv_count):
        tid = _uuid()
        num_vars = random.randint(Config.TEMPLATE_VARIABLES_MIN, Config.TEMPLATE_VARIABLES_MAX)
        # Alternate between email and sms
        ttype = NOTIFICATION_TYPE_EMAIL if i % 3 != 0 else NOTIFICATION_TYPE_SMS
        content = _template_content(num_vars, ttype)
        chosen_vars = random.sample(VARIABLE_NAMES, min(num_vars, len(VARIABLE_NAMES)))
        subject = _template_subject(num_vars, chosen_vars) if ttype == NOTIFICATION_TYPE_EMAIL else None

        session.execute(
            text("""
            INSERT INTO templates (id, name, template_type, created_at, content, subject,
                                   archived, hidden, service_id, created_by_id, version, process_type)
            VALUES (:id, :name, :ttype, :now, :content, :subject,
                    false, false, :sid, :cid, 1, 'normal')
        """),
            {
                "id": str(tid),
                "name": f"{PREFIX}-template-{i+1}",
                "ttype": ttype,
                "now": datetime.now(timezone.utc),
                "content": content,
                "subject": subject,
                "sid": str(service_id),
                "cid": str(creator_id),
            },
        )

        # templates_history row (version 1)
        session.execute(
            text("""
            INSERT INTO templates_history (id, name, template_type, created_at, content, subject,
                                           archived, hidden, service_id, created_by_id, version, process_type)
            VALUES (:id, :name, :ttype, :now, :content, :subject,
                    false, false, :sid, :cid, 1, 'normal')
        """),
            {
                "id": str(tid),
                "name": f"{PREFIX}-template-{i+1}",
                "ttype": ttype,
                "now": datetime.now(timezone.utc),
                "content": content,
                "subject": subject,
                "sid": str(service_id),
                "cid": str(creator_id),
            },
        )

        # template_folder_map association
        session.execute(
            text("""
            INSERT INTO template_folder_map (template_id, template_folder_id)
            VALUES (:tid, :fid)
        """),
            {"tid": str(tid), "fid": str(folder_ids[0])},
        )

        all_template_ids.append(tid)
        if ttype == NOTIFICATION_TYPE_EMAIL:
            email_template_ids.append(tid)
        else:
            sms_template_ids.append(tid)

        if (i + 1) % 500 == 0:
            print(f"    ... {i+1}/{hv_count} templates created")
            session.flush()

    # Other folders: small number of templates each
    for fi, fid in enumerate(folder_ids[1:], start=2):
        count = Config.OTHER_FOLDER_TEMPLATE_COUNT
        print(f"  Creating {count} templates in folder {fi}...")
        for j in range(count):
            tid = _uuid()
            num_vars = random.randint(Config.TEMPLATE_VARIABLES_MIN, Config.TEMPLATE_VARIABLES_MAX)
            ttype = NOTIFICATION_TYPE_EMAIL if j % 2 == 0 else NOTIFICATION_TYPE_SMS
            content = _template_content(num_vars, ttype)
            chosen_vars = random.sample(VARIABLE_NAMES, min(num_vars, len(VARIABLE_NAMES)))
            subject = _template_subject(num_vars, chosen_vars) if ttype == NOTIFICATION_TYPE_EMAIL else None

            session.execute(
                text("""
                INSERT INTO templates (id, name, template_type, created_at, content, subject,
                                       archived, hidden, service_id, created_by_id, version, process_type)
                VALUES (:id, :name, :ttype, :now, :content, :subject,
                        false, false, :sid, :cid, 1, 'normal')
            """),
                {
                    "id": str(tid),
                    "name": f"{PREFIX}-folder{fi}-template-{j+1}",
                    "ttype": ttype,
                    "now": datetime.now(timezone.utc),
                    "content": content,
                    "subject": subject,
                    "sid": str(service_id),
                    "cid": str(creator_id),
                },
            )

            session.execute(
                text("""
                INSERT INTO templates_history (id, name, template_type, created_at, content, subject,
                                               archived, hidden, service_id, created_by_id, version, process_type)
                VALUES (:id, :name, :ttype, :now, :content, :subject,
                        false, false, :sid, :cid, 1, 'normal')
            """),
                {
                    "id": str(tid),
                    "name": f"{PREFIX}-folder{fi}-template-{j+1}",
                    "ttype": ttype,
                    "now": datetime.now(timezone.utc),
                    "content": content,
                    "subject": subject,
                    "sid": str(service_id),
                    "cid": str(creator_id),
                },
            )

            session.execute(
                text("""
                INSERT INTO template_folder_map (template_id, template_folder_id)
                VALUES (:tid, :fid)
            """),
                {"tid": str(tid), "fid": str(fid)},
            )

            all_template_ids.append(tid)
            if ttype == NOTIFICATION_TYPE_EMAIL:
                email_template_ids.append(tid)
            else:
                sms_template_ids.append(tid)

    print(f"  Total templates: {len(all_template_ids)} (email: {len(email_template_ids)}, sms: {len(sms_template_ids)})")
    return all_template_ids, email_template_ids, sms_template_ids


def create_jobs(session, service_id, email_template_ids, sms_template_ids, creator_id, api_key_id):
    """Create job records to simulate bulk sends."""
    job_ids = []
    all_templates = [(t, NOTIFICATION_TYPE_EMAIL) for t in email_template_ids[:10]] + [
        (t, NOTIFICATION_TYPE_SMS) for t in sms_template_ids[:10]
    ]
    if not all_templates:
        print("  WARNING: No templates available — skipping jobs.")
        return job_ids

    print(f"  Creating {Config.NUM_JOBS} jobs...")
    start = Config.date_start_parsed()
    end = Config.date_end_parsed()
    for i in range(Config.NUM_JOBS):
        jid = _uuid()
        tmpl_id, ntype = random.choice(all_templates)
        created = _random_date(start, end)
        session.execute(
            text("""
            INSERT INTO jobs (id, original_file_name, service_id, template_id, template_version,
                              notification_count, notifications_sent, notifications_delivered,
                              notifications_failed, processing_started, processing_finished,
                              created_at, created_by_id, api_key_id, job_status, archived)
            VALUES (:id, :fname, :sid, :tid, 1,
                    :count, :count, :delivered, :failed, :started, :finished,
                    :created, :created_by, :api_key, 'finished', false)
        """),
            {
                "id": str(jid),
                "fname": f"{PREFIX}-job-{i+1}.csv",
                "sid": str(service_id),
                "tid": str(tmpl_id),
                "count": Config.JOB_NOTIFICATION_COUNT,
                "delivered": int(Config.JOB_NOTIFICATION_COUNT * 0.97),
                "failed": int(Config.JOB_NOTIFICATION_COUNT * 0.03),
                "started": created,
                "finished": created + timedelta(minutes=random.randint(5, 60)),
                "created": created,
                "created_by": str(creator_id),
                "api_key": str(api_key_id) if api_key_id else None,
            },
        )
        job_ids.append({"id": jid, "template_id": tmpl_id, "type": ntype, "created_at": created})

        if (i + 1) % 50 == 0:
            print(f"    ... {i+1}/{Config.NUM_JOBS} jobs created")

    return job_ids


def _build_notification_batch(
    batch_size,
    service_id,
    template_ids,
    notification_type,
    num_failed_remaining,
    num_remaining,
    job_ids,
    api_key_id,
    start_date,
    end_date,
):
    """Build a list of parameter dicts for a batch of notification_history inserts."""
    rows = []
    type_jobs = [j for j in job_ids if j["type"] == notification_type] if job_ids else []

    for _ in range(batch_size):
        # Force remaining failures into the last rows to guarantee exact totals
        if num_failed_remaining >= num_remaining:
            is_failed = True
        elif num_failed_remaining > 0:
            is_failed = random.random() < (num_failed_remaining / max(num_remaining, 1))
        else:
            is_failed = False
        status = "permanent-failure" if is_failed else "delivered"
        if is_failed:
            num_failed_remaining -= 1
        num_remaining -= 1

        tmpl_id = random.choice(template_ids)
        created = _random_date(start_date, end_date)
        job = random.choice(type_jobs) if type_jobs and random.random() < 0.7 else None

        rows.append(
            {
                "id": str(_uuid()),
                "service_id": str(service_id),
                "template_id": str(tmpl_id),
                "template_version": 1,
                "notification_type": notification_type,
                "created_at": created,
                "sent_at": created + timedelta(seconds=random.randint(1, 30)),
                "updated_at": created + timedelta(seconds=random.randint(31, 120)),
                "notification_status": status,
                "key_type": "normal",
                "billable_units": 1,
                "international": False,
                "api_key_id": str(api_key_id) if api_key_id else None,
                "job_id": str(job["id"]) if job else None,
                "job_row_number": random.randint(0, Config.JOB_NOTIFICATION_COUNT - 1) if job else None,
                "client_reference": PREFIX,
            }
        )

    return rows, num_failed_remaining, num_remaining


def insert_notification_history(session, service_id, email_template_ids, sms_template_ids, job_ids, api_key_id):
    """Bulk-insert notification_history rows using PostgreSQL COPY."""
    start_date = Config.date_start_parsed()
    end_date = Config.date_end_parsed()

    nh_columns = [
        "id",
        "service_id",
        "template_id",
        "template_version",
        "notification_type",
        "created_at",
        "sent_at",
        "updated_at",
        "notification_status",
        "key_type",
        "billable_units",
        "international",
        "api_key_id",
        "job_id",
        "job_row_number",
        "client_reference",
    ]

    for ntype, template_ids, total, failed_count in [
        (NOTIFICATION_TYPE_EMAIL, email_template_ids, Config.NUM_EMAILS_TOTAL, Config.NUM_EMAILS_FAILED),
        (NOTIFICATION_TYPE_SMS, sms_template_ids, Config.NUM_SMS_TOTAL, Config.NUM_SMS_FAILED),
    ]:
        if not template_ids:
            print(f"  WARNING: No {ntype} templates — skipping {ntype} notifications.")
            continue

        num_batches = math.ceil(total / Config.BATCH_SIZE)
        print(f"\n  Inserting {total:,} {ntype} notification_history rows ({failed_count:,} permanent-failure)...")
        print(f"    Batches: {num_batches} x {Config.BATCH_SIZE:,} (using COPY)")

        remaining = total
        failed_remaining = failed_count

        for batch_idx in range(num_batches):
            batch_size = min(Config.BATCH_SIZE, remaining)
            rows, failed_remaining, remaining = _build_notification_batch(
                batch_size,
                service_id,
                template_ids,
                ntype,
                failed_remaining,
                remaining,
                job_ids,
                api_key_id,
                start_date,
                end_date,
            )

            if rows:
                _copy_rows(session, "notification_history", nh_columns, rows)

            session.commit()
            pct = ((batch_idx + 1) / num_batches) * 100
            print(f"    ... batch {batch_idx+1}/{num_batches} ({pct:.1f}%) [{_timestamp()}]")


def insert_live_notifications(session, service_id, email_template_ids, sms_template_ids, job_ids, api_key_id, total_count):
    """Insert recent notifications into the live notifications table (last 7 days).

    The notifications table holds recent/active notifications, while notification_history holds the archive.
    """
    start_date = datetime.now(timezone.utc) - timedelta(days=7)
    end_date = datetime.now(timezone.utc)

    # Distribute across email and SMS proportionally
    total_emails = int(total_count * 0.4)  # 40% email
    total_sms = total_count - total_emails  # 60% SMS

    print(f"\n  Inserting {total_count:,} live notifications into 'notifications' table (last 7 days)...")
    print(
        f"    Split: {total_emails:,} email ({total_emails/total_count*100:.0f}%) + {total_sms:,} SMS ({total_sms/total_count*100:.0f}%)"
    )
    print("    Status distribution: ~95% delivered, ~5% permanent-failure (terminal statuses only)")

    notif_columns = [
        "id",
        "to",
        "normalised_to",
        "service_id",
        "template_id",
        "template_version",
        "notification_type",
        "created_at",
        "sent_at",
        "updated_at",
        "notification_status",
        "key_type",
        "billable_units",
        "international",
        "api_key_id",
        "job_id",
        "job_row_number",
        "client_reference",
    ]

    for ntype, template_ids, total in [
        (NOTIFICATION_TYPE_EMAIL, email_template_ids, total_emails),
        (NOTIFICATION_TYPE_SMS, sms_template_ids, total_sms),
    ]:
        if not template_ids or total == 0:
            continue

        type_jobs = [j for j in job_ids if j["type"] == ntype] if job_ids else []
        rows = []

        print(f"\n    Generating {total:,} {ntype} notifications... (using COPY)")

        for i in range(total):
            tmpl_id = random.choice(template_ids)
            created = _random_date(start_date.date(), end_date.date())
            job = random.choice(type_jobs) if type_jobs and random.random() < 0.7 else None

            # Only use terminal statuses to avoid Celery tasks (timeout_notifications,
            # replay_created_notifications) picking up fake rows and raising errors.
            status_roll = random.random()
            if status_roll < 0.95:
                status = "delivered"
            else:
                status = "permanent-failure"

            to_address = f"test-{i}@{FAKE_EMAIL_DOMAIN}" if ntype == NOTIFICATION_TYPE_EMAIL else FAKE_PHONE

            rows.append(
                {
                    "id": str(_uuid()),
                    "to": to_address,
                    "normalised_to": to_address.lower() if ntype == NOTIFICATION_TYPE_EMAIL else FAKE_PHONE,
                    "service_id": str(service_id),
                    "template_id": str(tmpl_id),
                    "template_version": 1,
                    "notification_type": ntype,
                    "created_at": created,
                    "sent_at": created + timedelta(seconds=random.randint(1, 30)) if status != "created" else None,
                    "updated_at": created + timedelta(seconds=random.randint(31, 120)),
                    "notification_status": status,
                    "key_type": "normal",
                    "billable_units": 1,
                    "international": False,
                    "api_key_id": str(api_key_id) if api_key_id else None,
                    "job_id": str(job["id"]) if job else None,
                    "job_row_number": random.randint(0, Config.JOB_NOTIFICATION_COUNT - 1) if job else None,
                    "client_reference": PREFIX,
                }
            )

            if len(rows) >= Config.BATCH_SIZE:
                _copy_rows(session, "notifications", notif_columns, rows)
                session.commit()
                pct = ((i + 1) / total) * 100
                print(f"      ... {i+1:,}/{total:,} ({pct:.1f}%) [{_timestamp()}]")
                rows = []

        if rows:
            _copy_rows(session, "notifications", notif_columns, rows)
            session.commit()
            print(f"      ... {total:,}/{total:,} (100.0%) [{_timestamp()}]")

    print(f"\n  ✓ Live notifications table populated ({total_count:,} rows).")


def _distribute_over_days(total, num_days, day_index):
    """Distribute total evenly across days, spreading the remainder across the first days."""
    base = total // num_days
    remainder = total % num_days
    return base + (1 if day_index < remainder else 0)


def populate_ft_notification_status(session, service_id, email_template_ids, sms_template_ids):
    """Aggregate notification_history data into ft_notification_status for dashboards."""
    start_date = datetime.combine(Config.date_start_parsed(), datetime.min.time())
    end_date = datetime.combine(Config.date_end_parsed(), datetime.min.time())
    dates = list(rrule.rrule(freq=rrule.DAILY, dtstart=start_date, until=end_date))

    total_email_delivered = Config.NUM_EMAILS_TOTAL - Config.NUM_EMAILS_FAILED
    total_email_failed = Config.NUM_EMAILS_FAILED
    total_sms_delivered = Config.NUM_SMS_TOTAL - Config.NUM_SMS_FAILED
    total_sms_failed = Config.NUM_SMS_FAILED

    num_days = len(dates)
    null_job_id = "00000000-0000-0000-0000-000000000000"

    ft_columns = [
        "bst_date",
        "template_id",
        "service_id",
        "job_id",
        "notification_type",
        "key_type",
        "notification_status",
        "notification_count",
        "billable_units",
        "created_at",
    ]

    print(f"\n  Populating ft_notification_status over {num_days} days... (using COPY)")

    rows = []
    for day_index, d in enumerate(dates):
        bst_date = d.date()
        for ntype, template_ids, delivered_total, failed_total in [
            (NOTIFICATION_TYPE_EMAIL, email_template_ids, total_email_delivered, total_email_failed),
            (NOTIFICATION_TYPE_SMS, sms_template_ids, total_sms_delivered, total_sms_failed),
        ]:
            if not template_ids:
                continue
            tmpl_id = random.choice(template_ids)
            daily_delivered = _distribute_over_days(delivered_total, num_days, day_index)
            daily_failed = _distribute_over_days(failed_total, num_days, day_index)

            if daily_delivered > 0:
                rows.append(
                    {
                        "bst_date": bst_date,
                        "template_id": str(tmpl_id),
                        "service_id": str(service_id),
                        "job_id": null_job_id,
                        "notification_type": ntype,
                        "key_type": "normal",
                        "notification_status": "delivered",
                        "notification_count": daily_delivered,
                        "billable_units": daily_delivered,
                        "created_at": datetime.now(timezone.utc),
                    }
                )
            if daily_failed > 0:
                rows.append(
                    {
                        "bst_date": bst_date,
                        "template_id": str(tmpl_id),
                        "service_id": str(service_id),
                        "job_id": null_job_id,
                        "notification_type": ntype,
                        "key_type": "normal",
                        "notification_status": "permanent-failure",
                        "notification_count": daily_failed,
                        "billable_units": daily_failed,
                        "created_at": datetime.now(timezone.utc),
                    }
                )

        if len(rows) >= 5000:
            _copy_rows(session, "ft_notification_status", ft_columns, rows)
            rows = []

    if rows:
        _copy_rows(session, "ft_notification_status", ft_columns, rows)

    session.commit()
    print("  ft_notification_status populated.")


def populate_ft_billing(session, service_id, email_template_ids, sms_template_ids):
    """Populate ft_billing aggregate table."""
    start_date = datetime.combine(Config.date_start_parsed(), datetime.min.time())
    end_date = datetime.combine(Config.date_end_parsed(), datetime.min.time())
    dates = list(rrule.rrule(freq=rrule.DAILY, dtstart=start_date, until=end_date))
    num_days = len(dates)

    billing_columns = [
        "bst_date",
        "template_id",
        "service_id",
        "notification_type",
        "provider",
        "rate_multiplier",
        "international",
        "rate",
        "postage",
        "sms_sending_vehicle",
        "billable_units",
        "notifications_sent",
        "created_at",
    ]

    print(f"\n  Populating ft_billing over {num_days} days... (using COPY)")

    rows = []
    for day_index, d in enumerate(dates):
        bst_date = d.date()
        for ntype, template_ids, total, provider in [
            (NOTIFICATION_TYPE_EMAIL, email_template_ids, Config.NUM_EMAILS_TOTAL, "ses"),
            (NOTIFICATION_TYPE_SMS, sms_template_ids, Config.NUM_SMS_TOTAL, "sns"),
        ]:
            if not template_ids:
                continue
            tmpl_id = random.choice(template_ids)
            daily_sent = _distribute_over_days(total, num_days, day_index)
            rate = 0.0 if ntype == NOTIFICATION_TYPE_EMAIL else 0.02

            rows.append(
                {
                    "bst_date": bst_date,
                    "template_id": str(tmpl_id),
                    "service_id": str(service_id),
                    "notification_type": ntype,
                    "provider": provider,
                    "rate_multiplier": 1,
                    "international": False,
                    "rate": rate,
                    "postage": "none",
                    "sms_sending_vehicle": "long_code",
                    "billable_units": daily_sent,
                    "notifications_sent": daily_sent,
                    "created_at": datetime.now(timezone.utc),
                }
            )

        if len(rows) >= 5000:
            _copy_rows(session, "ft_billing", billing_columns, rows)
            rows = []

    if rows:
        _copy_rows(session, "ft_billing", billing_columns, rows)

    session.commit()
    print("  ft_billing populated.")


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def cleanup(session):
    """Remove all test-simulate-prod-data entities."""
    print(f"\n{'='*60}")
    print(f"CLEANUP: Removing all '{PREFIX}' data... [{_timestamp()}]")
    print(f"{'='*60}\n")

    # Build name patterns for services and orgs. Cleanup is limited to
    # namespaced test data — configured names must start with the test prefix.
    service_names = {f"{PREFIX}%"}
    org_names = {f"{PREFIX}%"}
    if Config.SERVICE_NAME:
        if not Config.SERVICE_NAME.startswith(PREFIX):
            raise click.ClickException(
                f"Refusing cleanup: SERVICE_NAME '{Config.SERVICE_NAME}' does not start with required prefix '{PREFIX}'."
            )
        service_names.add(Config.SERVICE_NAME)
    if Config.ORGANISATION_NAME:
        if not Config.ORGANISATION_NAME.startswith(PREFIX):
            raise click.ClickException(
                f"Refusing cleanup: ORGANISATION_NAME '{Config.ORGANISATION_NAME}' does not start with required prefix '{PREFIX}'."
            )
        org_names.add(Config.ORGANISATION_NAME)

    # Find the service(s)
    clauses = " OR ".join(f"name LIKE :p{i}" for i in range(len(service_names)))
    params = {f"p{i}": n for i, n in enumerate(service_names)}
    result = session.execute(text(f"SELECT id FROM services WHERE {clauses}"), params)
    service_ids = [str(row[0]) for row in result]

    if not service_ids:
        print("No services found with prefix. Checking for orphaned users...")
    else:
        for sid in service_ids:
            print(f"\n  Cleaning service {sid}...")

            # notification_history
            print("    Deleting notification_history...")
            session.execute(text("DELETE FROM notification_history WHERE service_id = :sid"), {"sid": sid})

            # notifications (live table)
            print("    Deleting notifications...")
            session.execute(text("DELETE FROM notifications WHERE service_id = :sid"), {"sid": sid})

            # ft_notification_status
            print("    Deleting ft_notification_status...")
            session.execute(text("DELETE FROM ft_notification_status WHERE service_id = :sid"), {"sid": sid})

            # ft_billing
            print("    Deleting ft_billing...")
            session.execute(text("DELETE FROM ft_billing WHERE service_id = :sid"), {"sid": sid})

            # jobs
            print("    Deleting jobs...")
            session.execute(text("DELETE FROM jobs WHERE service_id = :sid"), {"sid": sid})

            # template_folder_map (via templates)
            print("    Deleting template_folder_map...")
            session.execute(
                text("""
                DELETE FROM template_folder_map WHERE template_id IN (
                    SELECT id FROM templates WHERE service_id = :sid
                )
            """),
                {"sid": sid},
            )

            # templates_history
            print("    Deleting templates_history...")
            session.execute(text("DELETE FROM templates_history WHERE service_id = :sid"), {"sid": sid})

            # templates
            print("    Deleting templates...")
            session.execute(text("DELETE FROM templates WHERE service_id = :sid"), {"sid": sid})

            # user_folder_permissions (before template_folder due to FK constraint)
            print("    Deleting user_folder_permissions...")
            session.execute(
                text("""
                DELETE FROM user_folder_permissions WHERE template_folder_id IN (
                    SELECT id FROM template_folder WHERE service_id = :sid
                )
            """),
                {"sid": sid},
            )

            # template_folder
            print("    Deleting template_folder...")
            session.execute(text("DELETE FROM template_folder WHERE service_id = :sid"), {"sid": sid})

            # service_callback_api
            print("    Deleting service_callback_api...")
            session.execute(text("DELETE FROM service_callback_api WHERE service_id = :sid"), {"sid": sid})

            # service_email_reply_to
            print("    Deleting service_email_reply_to...")
            session.execute(text("DELETE FROM service_email_reply_to WHERE service_id = :sid"), {"sid": sid})

            # annual_billing
            print("    Deleting annual_billing...")
            session.execute(text("DELETE FROM annual_billing WHERE service_id = :sid"), {"sid": sid})

            # service_sms_senders
            print("    Deleting service_sms_senders...")
            session.execute(text("DELETE FROM service_sms_senders WHERE service_id = :sid"), {"sid": sid})

            # api_keys
            print("    Deleting api_keys...")
            session.execute(text("DELETE FROM api_keys WHERE service_id = :sid"), {"sid": sid})

            # permissions
            print("    Deleting permissions...")
            session.execute(text("DELETE FROM permissions WHERE service_id = :sid"), {"sid": sid})

            # service_permissions
            print("    Deleting service_permissions...")
            session.execute(text("DELETE FROM service_permissions WHERE service_id = :sid"), {"sid": sid})

            # user_to_service
            print("    Deleting user_to_service...")
            session.execute(text("DELETE FROM user_to_service WHERE service_id = :sid"), {"sid": sid})

            # service
            print("    Deleting services_history...")
            session.execute(text("DELETE FROM services_history WHERE id = :sid"), {"sid": sid})
            print("    Deleting service...")
            session.execute(text("DELETE FROM services WHERE id = :sid"), {"sid": sid})

    # Users
    print("\n  Deleting users...")
    session.execute(text("DELETE FROM users WHERE email_address LIKE :pattern"), {"pattern": f"{PREFIX}%"})

    # Organisation
    print("  Deleting organisation...")
    for org_name in org_names:
        session.execute(text("DELETE FROM organisation WHERE name LIKE :pattern"), {"pattern": org_name})

    session.commit()
    print(f"\nCleanup complete. [{_timestamp()}]")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


@click.command()
@click.option(
    "--cleanup-only", is_flag=True, default=False, help="Only run cleanup (delete all test-simulate-prod-data entities)"
)
@click.option(
    "--skip-notifications", is_flag=True, default=False, help="Skip notification_history generation (for testing setup)"
)
@click.option("--skip-aggregates", is_flag=True, default=False, help="Skip ft_notification_status and ft_billing generation")
@click.option(
    "--only-notifications-and-aggregates",
    is_flag=True,
    default=False,
    help="Skip setup objects, only generate notification_history, ft_notification_status, and ft_billing",
)
@click.option(
    "--quick-100000",
    is_flag=True,
    default=False,
    help="Use quick 100K preset (~185K notifications total for fast testing)",
)
def main(cleanup_only, skip_notifications, skip_aggregates, only_notifications_and_aggregates, quick_100000):
    """Generate production-like data for staging performance testing."""

    # Apply quick-100000 preset if requested
    if quick_100000:
        Config.NUM_EMAILS_TOTAL = Config.NUM_EMAILS_TOTAL_QUICK_100K
        Config.NUM_EMAILS_FAILED = Config.NUM_EMAILS_FAILED_QUICK_100K
        Config.NUM_SMS_TOTAL = Config.NUM_SMS_TOTAL_QUICK_100K
        Config.NUM_SMS_FAILED = Config.NUM_SMS_FAILED_QUICK_100K
        Config.NUM_LIVE_NOTIFICATIONS = Config.NUM_LIVE_NOTIFICATIONS_QUICK_100K

    engine = get_engine()

    with Session(engine) as session:
        if cleanup_only:
            cleanup(session)
            return

        print(f"\n{'='*60}")
        print(f"GENERATE: Production-like data simulation [{_timestamp()}]")
        print(f"{'='*60}")
        print(f"  Prefix:       {PREFIX}")
        print(f"  Date range:   {Config.DATE_START} to {Config.DATE_END}")
        print(f"  Emails:       {Config.NUM_EMAILS_TOTAL:,} ({Config.NUM_EMAILS_FAILED:,} failed)")
        print(f"  SMS:          {Config.NUM_SMS_TOTAL:,} ({Config.NUM_SMS_FAILED:,} failed)")
        print(
            f"  Templates:    {Config.HIGH_VOLUME_FOLDER_TEMPLATE_COUNT + Config.OTHER_FOLDER_TEMPLATE_COUNT * (Config.NUM_TEMPLATE_FOLDERS - 1)}"
        )
        print(f"  Users:        {Config.NUM_USERS}")
        print(f"  Jobs:         {Config.NUM_JOBS}")
        print(f"{'='*60}\n")

        try:
            if only_notifications_and_aggregates:
                # Only generate notifications and aggregates for existing setup objects
                print("\n" + "=" * 60)
                print("MODE: Generating only notifications and aggregates")
                print("=" * 60 + "\n")

                # Find existing service
                result = session.execute(text("SELECT id FROM services WHERE name = :name"), {"name": Config.SERVICE_NAME})
                row = result.fetchone()
                if not row:
                    raise click.ClickException(
                        f"Service '{Config.SERVICE_NAME}' not found. Run without --only-notifications-and-aggregates first to create setup objects."
                    )
                service_id = row[0]

                # Find existing templates
                result = session.execute(
                    text("SELECT id, template_type FROM templates WHERE service_id = :sid ORDER BY created_at"),
                    {"sid": str(service_id)},
                )
                all_template_ids = []
                email_template_ids = []
                sms_template_ids = []
                for row in result:
                    tid = row[0]
                    ttype = row[1]
                    all_template_ids.append(tid)
                    if ttype == NOTIFICATION_TYPE_EMAIL:
                        email_template_ids.append(tid)
                    else:
                        sms_template_ids.append(tid)

                if not all_template_ids:
                    raise click.ClickException(
                        f"No templates found for service '{Config.SERVICE_NAME}'. Run without --only-notifications-and-aggregates first."
                    )

                print(f"  Found service: {service_id}")
                print(
                    f"  Found {len(all_template_ids)} templates (email: {len(email_template_ids)}, sms: {len(sms_template_ids)})"
                )

                # Find existing jobs
                result = session.execute(
                    text("SELECT id, template_id, created_at FROM jobs WHERE service_id = :sid ORDER BY created_at"),
                    {"sid": str(service_id)},
                )
                job_ids = []
                for row in result:
                    # Determine type from template
                    result2 = session.execute(text("SELECT template_type FROM templates WHERE id = :tid"), {"tid": str(row[1])})
                    ttype_row = result2.fetchone()
                    job_ids.append(
                        {
                            "id": row[0],
                            "template_id": row[1],
                            "type": ttype_row[0] if ttype_row else "email",
                            "created_at": row[2],
                        }
                    )

                print(f"  Found {len(job_ids)} jobs\\n")

                # Generate notifications
                print("Inserting notification_history...")
                insert_notification_history(session, service_id, email_template_ids, sms_template_ids, job_ids, None)

                print("\nInserting live notifications...")
                insert_live_notifications(
                    session, service_id, email_template_ids, sms_template_ids, job_ids, None, Config.NUM_LIVE_NOTIFICATIONS
                )

                # Generate aggregates
                print("\\n[Bonus] Populating aggregate tables...")
                populate_ft_notification_status(session, service_id, email_template_ids, sms_template_ids)
                populate_ft_billing(session, service_id, email_template_ids, sms_template_ids)

                print("\\nFinal commit...")
                session.commit()
                print("\\n" + "=" * 60)
                print("SUCCESS: Notifications and aggregates generated.")
                print(f"  Service ID: {service_id}")
                print("=" * 60)
                return

            # 1. Organisation
            print(f"[1/12] Creating organisation... [{_timestamp()}]")
            org_id = create_organisation(session)

            # 2. Users
            print(f"[2/12] Creating users... [{_timestamp()}]")
            users = create_users(session)

            # 3. Service
            print("[3/12] Creating service...")
            service_id = create_service(session, users, org_id)

            # 4. Link users
            print("[4/12] Linking users to service...")
            link_users_to_service(session, users, service_id)

            # 5. User permissions
            print("[5/12] Granting user permissions...")
            grant_user_permissions(session, users, service_id)

            # 6. Service permissions
            print("[6/12] Granting service permissions...")
            grant_service_permissions(session, service_id)

            # 7. API key
            print("[7/12] Creating API key...")
            api_key_id = create_api_key(session, service_id, users[0]["id"])

            # 8. Reply-to and callback
            print("[8/12] Creating reply-to and callback...")
            create_reply_to(session, service_id)
            create_callback(session, service_id, users[0]["id"])

            # 8b. Annual billing and SMS sender
            create_annual_billing(session, service_id)
            create_sms_sender(session, service_id)

            # 9. Template folders
            print("[9/12] Creating template folders...")
            folder_ids, folder_names = create_template_folders(session, service_id)

            # 9b. Grant folder permissions
            print("[9b/12] Granting folder permissions...")
            grant_folder_permissions(session, users, service_id, folder_ids)

            # 9c. Link existing user (optional — set LINK_EXISTING_USER_EMAIL in .env)
            link_existing_user(session, service_id, folder_ids)

            # 10. Templates
            print("[10/12] Creating templates...")
            all_template_ids, email_template_ids, sms_template_ids = create_templates(
                session, service_id, users[0]["id"], folder_ids
            )

            # Flush before notifications so FKs are available
            session.commit()
            print("\n  Setup objects committed.\n")

            # 11. Jobs
            print("[11/12] Creating jobs...")
            job_ids = create_jobs(session, service_id, email_template_ids, sms_template_ids, users[0]["id"], api_key_id)

            session.commit()
            print("  Jobs committed.\n")

            # 12. Notifications
            if not skip_notifications:
                print(f"[12/12] Inserting notification_history... [{_timestamp()}]")
                insert_notification_history(session, service_id, email_template_ids, sms_template_ids, job_ids, api_key_id)
                print(f"\n[12b/12] Inserting live notifications... [{_timestamp()}]")
                insert_live_notifications(
                    session, service_id, email_template_ids, sms_template_ids, job_ids, api_key_id, Config.NUM_LIVE_NOTIFICATIONS
                )
            else:
                print("[12/12] Skipping notification_history (--skip-notifications)")

            # Aggregate tables
            if not skip_aggregates:
                print(f"\n[Bonus] Populating aggregate tables... [{_timestamp()}]")
                populate_ft_notification_status(session, service_id, email_template_ids, sms_template_ids)
                populate_ft_billing(session, service_id, email_template_ids, sms_template_ids)
            else:
                print("\n[Bonus] Skipping aggregates (--skip-aggregates)")

            print(f"\nFinal commit... [{_timestamp()}]")
            session.commit()
            print("\n" + "=" * 60)
            print(f"SUCCESS: All data generated. [{_timestamp()}]")
            print(f"  Service ID: {service_id}")
            print(f"  Service Name: {Config.SERVICE_NAME}")
            print(f"  Organisation ID: {org_id}")
            if not skip_notifications:
                print("\n  Notification Summary:")
                print(f"    notification_history: {Config.NUM_EMAILS_TOTAL + Config.NUM_SMS_TOTAL:,} rows")
                print(f"      - Email: {Config.NUM_EMAILS_TOTAL:,} ({Config.NUM_EMAILS_FAILED:,} failed)")
                print(f"      - SMS: {Config.NUM_SMS_TOTAL:,} ({Config.NUM_SMS_FAILED:,} failed)")
                print(f"    notifications (live): {Config.NUM_LIVE_NOTIFICATIONS:,} rows (last 7 days)")
                print(f"      - Email: {int(Config.NUM_LIVE_NOTIFICATIONS * 0.4):,} (40%)")
                print(f"      - SMS: {int(Config.NUM_LIVE_NOTIFICATIONS * 0.6):,} (60%)")
            print("=" * 60)

        except Exception as e:
            print(f"\nERROR: {e}")
            print("Rolling back...")
            session.rollback()
            raise


if __name__ == "__main__":
    main()
