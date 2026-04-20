"""
test-simulate-prod-data: Generate non-PII production-like data in a staging database.

Usage:
    python generate.py               # populate data
    python generate.py --cleanup-only  # remove all test-simulate-prod-data entities

Requires SQLALCHEMY_DATABASE_URI env var (or .env file).
"""

import math
import random
import uuid
from datetime import datetime, timedelta, timezone

import click
from dateutil import rrule
from sim_config import PREFIX, Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

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
    return create_engine(Config.SQLALCHEMY_DATABASE_URI, echo=False)


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
                    :now, 'active', 'email_auth', :now, false,
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


def create_api_key(session, service_id, creator_id):
    key_id = _uuid()
    print(f"  Creating API key ({key_id})...")
    session.execute(
        text("""
        INSERT INTO api_keys (id, name, secret, service_id, key_type, created_by_id, created_at, version)
        VALUES (:id, :name, :secret, :sid, 'normal', :created_by, :now, 1)
    """),
        {
            "id": str(key_id),
            "name": f"{PREFIX}-api-key",
            "secret": str(_uuid()),  # not a real signed secret; for data volume simulation only
            "sid": str(service_id),
            "created_by": str(creator_id),
            "now": datetime.now(timezone.utc),
        },
    )
    return key_id


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
    cb_id = _uuid()
    print(f"  Creating service callback ({cb_id})...")
    session.execute(
        text("""
        INSERT INTO service_callback_api (id, service_id, url, callback_type, bearer_token,
                                          created_at, updated_by_id, version)
        VALUES (:id, :sid, :url, 'delivery_status', :bearer, :now, :updated_by, 1)
    """),
        {
            "id": str(cb_id),
            "sid": str(service_id),
            "url": f"https://{PREFIX}.example.com/callback",
            "bearer": "simulated-bearer-token",
            "now": datetime.now(timezone.utc),
            "updated_by": str(creator_id),
        },
    )
    return cb_id


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
                "api_key": str(api_key_id),
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
                "api_key_id": str(api_key_id),
                "job_id": str(job["id"]) if job else None,
                "job_row_number": random.randint(0, Config.JOB_NOTIFICATION_COUNT - 1) if job else None,
                "client_reference": PREFIX,
            }
        )

    return rows, num_failed_remaining, num_remaining


def insert_notification_history(session, service_id, email_template_ids, sms_template_ids, job_ids, api_key_id):
    """Bulk-insert notification_history rows."""
    start_date = Config.date_start_parsed()
    end_date = Config.date_end_parsed()

    for ntype, template_ids, total, failed_count in [
        (NOTIFICATION_TYPE_EMAIL, email_template_ids, Config.NUM_EMAILS_TOTAL, Config.NUM_EMAILS_FAILED),
        (NOTIFICATION_TYPE_SMS, sms_template_ids, Config.NUM_SMS_TOTAL, Config.NUM_SMS_FAILED),
    ]:
        if not template_ids:
            print(f"  WARNING: No {ntype} templates — skipping {ntype} notifications.")
            continue

        num_batches = math.ceil(total / Config.BATCH_SIZE)
        print(f"\n  Inserting {total:,} {ntype} notification_history rows ({failed_count:,} permanent-failure)...")
        print(f"    Batches: {num_batches} x {Config.BATCH_SIZE:,}")

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

            # Use raw SQL multi-row insert for maximum speed
            if rows:
                session.execute(
                    text("""
                    INSERT INTO notification_history
                        (id, service_id, template_id, template_version,
                         notification_type, created_at, sent_at, updated_at, notification_status, key_type,
                         billable_units, international, api_key_id, job_id, job_row_number,
                         client_reference)
                    VALUES
                        (:id, :service_id, :template_id, :template_version,
                         :notification_type, :created_at, :sent_at, :updated_at, :notification_status, :key_type,
                         :billable_units, :international, :api_key_id, :job_id, :job_row_number,
                         :client_reference)
                """),
                    rows,
                )

            if (batch_idx + 1) % 10 == 0 or batch_idx == num_batches - 1:
                pct = ((batch_idx + 1) / num_batches) * 100
                print(f"    ... batch {batch_idx+1}/{num_batches} ({pct:.1f}%)")
                session.commit()


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

    print(f"\n  Populating ft_notification_status over {num_days} days...")

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
            session.execute(
                text("""
                INSERT INTO ft_notification_status
                    (bst_date, template_id, service_id, job_id, notification_type, key_type,
                     notification_status, notification_count, billable_units, created_at)
                VALUES
                    (:bst_date, :template_id, :service_id, :job_id, :notification_type, :key_type,
                     :notification_status, :notification_count, :billable_units, :created_at)
            """),
                rows,
            )
            rows = []

    if rows:
        session.execute(
            text("""
            INSERT INTO ft_notification_status
                (bst_date, template_id, service_id, job_id, notification_type, key_type,
                 notification_status, notification_count, billable_units, created_at)
            VALUES
                (:bst_date, :template_id, :service_id, :job_id, :notification_type, :key_type,
                 :notification_status, :notification_count, :billable_units, :created_at)
        """),
            rows,
        )

    print("  ft_notification_status populated.")


def populate_ft_billing(session, service_id, email_template_ids, sms_template_ids):
    """Populate ft_billing aggregate table."""
    start_date = datetime.combine(Config.date_start_parsed(), datetime.min.time())
    end_date = datetime.combine(Config.date_end_parsed(), datetime.min.time())
    dates = list(rrule.rrule(freq=rrule.DAILY, dtstart=start_date, until=end_date))
    num_days = len(dates)

    print(f"\n  Populating ft_billing over {num_days} days...")

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
            session.execute(
                text("""
                INSERT INTO ft_billing
                    (bst_date, template_id, service_id, notification_type, provider,
                     rate_multiplier, international, rate, postage, sms_sending_vehicle,
                     billable_units, notifications_sent, created_at)
                VALUES
                    (:bst_date, :template_id, :service_id, :notification_type, :provider,
                     :rate_multiplier, :international, :rate, :postage, :sms_sending_vehicle,
                     :billable_units, :notifications_sent, :created_at)
            """),
                rows,
            )
            rows = []

    if rows:
        session.execute(
            text("""
            INSERT INTO ft_billing
                (bst_date, template_id, service_id, notification_type, provider,
                 rate_multiplier, international, rate, postage, sms_sending_vehicle,
                 billable_units, notifications_sent, created_at)
            VALUES
                (:bst_date, :template_id, :service_id, :notification_type, :provider,
                 :rate_multiplier, :international, :rate, :postage, :sms_sending_vehicle,
                 :billable_units, :notifications_sent, :created_at)
        """),
            rows,
        )

    print("  ft_billing populated.")


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------


def cleanup(session):
    """Remove all test-simulate-prod-data entities."""
    print(f"\n{'='*60}")
    print(f"CLEANUP: Removing all '{PREFIX}' data...")
    print(f"{'='*60}\n")

    # Build name patterns for services and orgs (configured names may not include PREFIX)
    service_names = {f"{PREFIX}%"}
    org_names = {f"{PREFIX}%"}
    if Config.SERVICE_NAME and not Config.SERVICE_NAME.startswith(PREFIX):
        service_names.add(Config.SERVICE_NAME)
    if Config.ORGANISATION_NAME and not Config.ORGANISATION_NAME.startswith(PREFIX):
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

            # template_folder
            print("    Deleting template_folder...")
            session.execute(text("DELETE FROM template_folder WHERE service_id = :sid"), {"sid": sid})

            # service_callback_api
            print("    Deleting service_callback_api...")
            session.execute(text("DELETE FROM service_callback_api WHERE service_id = :sid"), {"sid": sid})

            # service_email_reply_to
            print("    Deleting service_email_reply_to...")
            session.execute(text("DELETE FROM service_email_reply_to WHERE service_id = :sid"), {"sid": sid})

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
    print("\nCleanup complete.")


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
def main(cleanup_only, skip_notifications, skip_aggregates):
    """Generate production-like data for staging performance testing."""
    engine = get_engine()

    with Session(engine) as session:
        if cleanup_only:
            cleanup(session)
            return

        print(f"\n{'='*60}")
        print("GENERATE: Production-like data simulation")
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
            # 1. Organisation
            print("[1/12] Creating organisation...")
            org_id = create_organisation(session)

            # 2. Users
            print("[2/12] Creating users...")
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

            # 9. Template folders
            print("[9/12] Creating template folders...")
            folder_ids, folder_names = create_template_folders(session, service_id)

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
                print("[12/12] Inserting notification_history...")
                insert_notification_history(session, service_id, email_template_ids, sms_template_ids, job_ids, api_key_id)
            else:
                print("[12/12] Skipping notification_history (--skip-notifications)")

            # Aggregate tables
            if not skip_aggregates:
                print("\n[Bonus] Populating aggregate tables...")
                populate_ft_notification_status(session, service_id, email_template_ids, sms_template_ids)
                populate_ft_billing(session, service_id, email_template_ids, sms_template_ids)
            else:
                print("\n[Bonus] Skipping aggregates (--skip-aggregates)")

            print("\nFinal commit...")
            session.commit()
            print("\n" + "=" * 60)
            print("SUCCESS: All data generated.")
            print(f"  Service ID: {service_id}")
            print(f"  Service Name: {Config.SERVICE_NAME}")
            print(f"  Organisation ID: {org_id}")
            print("=" * 60)

        except Exception as e:
            print(f"\nERROR: {e}")
            print("Rolling back...")
            session.rollback()
            raise


if __name__ == "__main__":
    main()
