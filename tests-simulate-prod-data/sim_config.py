import os
from datetime import date

from dotenv import load_dotenv

load_dotenv()

PREFIX = "test-simulate-prod-data"


class Config:
    """Configuration for the production data simulation script.

    All values can be overridden via environment variables.
    """

    # Database
    SQLALCHEMY_DATABASE_URI = os.environ.get("SQLALCHEMY_DATABASE_URI", "")

    # Service settings
    SERVICE_NAME = os.environ.get("SERVICE_NAME", f"{PREFIX}-service")
    SERVICE_EMAIL_FROM = os.environ.get("SERVICE_EMAIL_FROM", f"{PREFIX}@staging.local")
    SERVICE_SMS_ANNUAL_LIMIT = int(os.environ.get("SERVICE_SMS_ANNUAL_LIMIT", "10000000"))
    SERVICE_EMAIL_ANNUAL_LIMIT = int(os.environ.get("SERVICE_EMAIL_ANNUAL_LIMIT", "25000000"))
    SERVICE_MESSAGE_LIMIT = int(os.environ.get("SERVICE_MESSAGE_LIMIT", "250000"))
    SERVICE_SMS_DAILY_LIMIT = int(os.environ.get("SERVICE_SMS_DAILY_LIMIT", "100000"))
    SERVICE_RATE_LIMIT = int(os.environ.get("SERVICE_RATE_LIMIT", "3000"))

    # Users
    NUM_USERS = int(os.environ.get("NUM_USERS", "5"))

    # Template folders
    NUM_TEMPLATE_FOLDERS = int(os.environ.get("NUM_TEMPLATE_FOLDERS", "5"))
    HIGH_VOLUME_FOLDER_TEMPLATE_COUNT = int(os.environ.get("HIGH_VOLUME_FOLDER_TEMPLATE_COUNT", "2000"))
    OTHER_FOLDER_TEMPLATE_COUNT = int(os.environ.get("OTHER_FOLDER_TEMPLATE_COUNT", "5"))
    TEMPLATE_VARIABLES_MIN = int(os.environ.get("TEMPLATE_VARIABLES_MIN", "3"))
    TEMPLATE_VARIABLES_MAX = int(os.environ.get("TEMPLATE_VARIABLES_MAX", "5"))

    # Notifications — date range
    DATE_START = os.environ.get("DATE_START", "2025-04-01")
    DATE_END = os.environ.get("DATE_END", "2026-03-31")

    # Notifications — email
    NUM_EMAILS_TOTAL = int(os.environ.get("NUM_EMAILS_TOTAL", "5000000"))
    NUM_EMAILS_FAILED = int(os.environ.get("NUM_EMAILS_FAILED", "50000"))

    # Notifications — SMS
    NUM_SMS_TOTAL = int(os.environ.get("NUM_SMS_TOTAL", "9000000"))
    NUM_SMS_FAILED = int(os.environ.get("NUM_SMS_FAILED", "90000"))

    # Jobs
    NUM_JOBS = int(os.environ.get("NUM_JOBS", "200"))
    JOB_NOTIFICATION_COUNT = int(os.environ.get("JOB_NOTIFICATION_COUNT", "10000"))

    # Batch size for bulk inserts
    BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "10000"))

    # Organisation
    ORGANISATION_NAME = os.environ.get("ORGANISATION_NAME", f"{PREFIX}-org")

    @classmethod
    def date_start_parsed(cls):
        return date.fromisoformat(cls.DATE_START)

    @classmethod
    def date_end_parsed(cls):
        return date.fromisoformat(cls.DATE_END)

    @classmethod
    def validate(cls):
        errors = []

        if not cls.SQLALCHEMY_DATABASE_URI:
            errors.append("SQLALCHEMY_DATABASE_URI is required. Set it in .env or as an environment variable.")

        if not cls.DATE_START:
            errors.append("DATE_START is required (format: YYYY-MM-DD).")
        if not cls.DATE_END:
            errors.append("DATE_END is required (format: YYYY-MM-DD).")

        if cls.DATE_START and cls.DATE_END:
            try:
                start = cls.date_start_parsed()
                end = cls.date_end_parsed()
                if start >= end:
                    errors.append(f"DATE_START ({cls.DATE_START}) must be before DATE_END ({cls.DATE_END}).")
            except ValueError as e:
                errors.append(f"Invalid date format: {e}. Use YYYY-MM-DD.")

        if cls.NUM_USERS < 1:
            errors.append("NUM_USERS must be at least 1.")
        if cls.NUM_TEMPLATE_FOLDERS < 1:
            errors.append("NUM_TEMPLATE_FOLDERS must be at least 1.")
        if cls.BATCH_SIZE < 1:
            errors.append("BATCH_SIZE must be at least 1.")
        if cls.NUM_EMAILS_FAILED > cls.NUM_EMAILS_TOTAL:
            errors.append(
                f"NUM_EMAILS_FAILED ({cls.NUM_EMAILS_FAILED:,}) must be <= NUM_EMAILS_TOTAL ({cls.NUM_EMAILS_TOTAL:,})."
            )
        if cls.NUM_SMS_FAILED > cls.NUM_SMS_TOTAL:
            errors.append(f"NUM_SMS_FAILED ({cls.NUM_SMS_FAILED:,}) must be <= NUM_SMS_TOTAL ({cls.NUM_SMS_TOTAL:,}).")

        if errors:
            print("\n" + "=" * 60)
            print("CONFIGURATION ERRORS")
            print("=" * 60)
            for i, err in enumerate(errors, 1):
                print(f"  [{i}] {err}")
            print()
            print("Fix the above in your .env file or environment variables.")
            print("See .env.example for reference.")
            print("=" * 60 + "\n")
            raise SystemExit(1)

        # Log resolved config for visibility
        print("\n" + "-" * 60)
        print("Resolved configuration:")
        print("-" * 60)
        print(f"  SQLALCHEMY_DATABASE_URI : {'*' * 20} (set)")
        print(f"  SERVICE_NAME            : {cls.SERVICE_NAME}")
        print(f"  SERVICE_EMAIL_FROM      : {cls.SERVICE_EMAIL_FROM}")
        print(f"  SERVICE_SMS_ANNUAL_LIMIT: {cls.SERVICE_SMS_ANNUAL_LIMIT:,}")
        print(f"  SERVICE_EMAIL_ANNUAL_LIMIT: {cls.SERVICE_EMAIL_ANNUAL_LIMIT:,}")
        print(f"  NUM_USERS               : {cls.NUM_USERS}")
        print(f"  NUM_TEMPLATE_FOLDERS    : {cls.NUM_TEMPLATE_FOLDERS}")
        print(f"  HIGH_VOLUME_FOLDER_TEMPLATE_COUNT: {cls.HIGH_VOLUME_FOLDER_TEMPLATE_COUNT:,}")
        print(f"  DATE_START              : {cls.DATE_START}")
        print(f"  DATE_END                : {cls.DATE_END}")
        print(f"  NUM_EMAILS_TOTAL        : {cls.NUM_EMAILS_TOTAL:,}")
        print(f"  NUM_EMAILS_FAILED       : {cls.NUM_EMAILS_FAILED:,}")
        print(f"  NUM_SMS_TOTAL           : {cls.NUM_SMS_TOTAL:,}")
        print(f"  NUM_SMS_FAILED          : {cls.NUM_SMS_FAILED:,}")
        print(f"  NUM_JOBS                : {cls.NUM_JOBS}")
        print(f"  BATCH_SIZE              : {cls.BATCH_SIZE:,}")
        print(f"  ORGANISATION_NAME       : {cls.ORGANISATION_NAME}")
        print("-" * 60 + "\n")
