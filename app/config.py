from datetime import timedelta
import os
import json
from dotenv import load_dotenv

from celery.schedules import crontab
from kombu import Exchange, Queue

from fido2.server import Fido2Server, RelyingParty

load_dotenv()

if os.getenv('VCAP_SERVICES'):
    # on cloudfoundry, config is a json blob in VCAP_SERVICES - unpack it, and populate
    # standard environment variables from it
    from app.cloudfoundry_config import extract_cloudfoundry_config

    extract_cloudfoundry_config()


class QueueNames(object):
    PERIODIC = 'periodic-tasks'
    PRIORITY = 'priority-tasks'
    DATABASE = 'database-tasks'
    SEND_SMS = 'send-sms-tasks'
    SEND_EMAIL = 'send-email-tasks'
    RESEARCH_MODE = 'research-mode-tasks'
    REPORTING = 'reporting-tasks'
    JOBS = 'job-tasks'
    RETRY = 'retry-tasks'
    NOTIFY = 'notify-internal-tasks'
    PROCESS_FTP = 'process-ftp-tasks'
    CREATE_LETTERS_PDF = 'create-letters-pdf-tasks'
    CALLBACKS = 'service-callbacks'
    LETTERS = 'letter-tasks'
    ANTIVIRUS = 'antivirus-tasks'

    @staticmethod
    def all_queues():
        return [
            QueueNames.PRIORITY,
            QueueNames.PERIODIC,
            QueueNames.DATABASE,
            QueueNames.SEND_SMS,
            QueueNames.SEND_EMAIL,
            QueueNames.RESEARCH_MODE,
            QueueNames.REPORTING,
            QueueNames.JOBS,
            QueueNames.RETRY,
            QueueNames.NOTIFY,
            # QueueNames.CREATE_LETTERS_PDF,
            QueueNames.CALLBACKS,
            # QueueNames.LETTERS,
        ]


class TaskNames(object):
    PROCESS_INCOMPLETE_JOBS = 'process-incomplete-jobs'
    ZIP_AND_SEND_LETTER_PDFS = 'zip-and-send-letter-pdfs'
    SCAN_FILE = 'scan-file'


class Config(object):
    # URL of admin app
    ADMIN_BASE_URL = os.getenv('ADMIN_BASE_URL', 'http://localhost:6012')

    # URL of api app (on AWS this is the internal api endpoint)
    API_HOST_NAME = os.getenv('API_HOST_NAME')

    # admin app api key
    ADMIN_CLIENT_SECRET = os.getenv('ADMIN_CLIENT_SECRET')

    # encyption secret/salt
    SECRET_KEY = os.getenv('SECRET_KEY')
    DANGEROUS_SALT = os.getenv('DANGEROUS_SALT')

    # DB conection string
    SQLALCHEMY_DATABASE_URI = os.getenv('SQLALCHEMY_DATABASE_URI')

    # MMG API Key
    MMG_API_KEY = os.getenv('MMG_API_KEY')

    # Firetext API Key
    FIRETEXT_API_KEY = os.getenv("FIRETEXT_API_KEY")

    # Firetext simluation key
    LOADTESTING_API_KEY = os.getenv("LOADTESTING_API_KEY")

    # Hosted graphite statsd prefix
    STATSD_PREFIX = os.getenv('STATSD_PREFIX')

    # Prefix to identify queues in SQS
    NOTIFICATION_QUEUE_PREFIX = os.getenv('NOTIFICATION_QUEUE_PREFIX')

    # URL of redis instance
    REDIS_URL = os.getenv('REDIS_URL')
    REDIS_ENABLED = os.getenv('REDIS_ENABLED') == '1'
    EXPIRE_CACHE_TEN_MINUTES = 600
    EXPIRE_CACHE_EIGHT_DAYS = 8 * 24 * 60 * 60

    # Performance platform
    PERFORMANCE_PLATFORM_ENABLED = False
    PERFORMANCE_PLATFORM_URL = 'https://www.performance.service.gov.uk/data/govuk-notify/'

    # Zendesk
    ZENDESK_API_KEY = os.getenv('ZENDESK_API_KEY')

    # Freshdesk
    FRESH_DESK_API_URL = os.getenv('FRESH_DESK_API_URL')
    FRESH_DESK_API_KEY = os.getenv('FRESH_DESK_API_KEY')

    # Logging
    DEBUG = False
    NOTIFY_LOG_PATH = os.getenv('NOTIFY_LOG_PATH')

    # Cronitor
    CRONITOR_ENABLED = False
    CRONITOR_KEYS = json.loads(os.getenv('CRONITOR_KEYS', '{}'))

    # Antivirus
    MLWR_HOST = os.getenv("MLWR_HOST", False)
    MLWR_USER = os.getenv("MLWR_USER", "")
    MLWR_KEY = os.getenv("MLWR_KEY", "")

    # SendGrid
    SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY", "")

    # PII check
    SCAN_FOR_PII = os.getenv("SCAN_FOR_PII", False)

    ###########################
    # Default config values ###
    ###########################

    NOTIFY_ENVIRONMENT = os.getenv("NOTIFY_ENVIRONMENT", "development")
    ADMIN_CLIENT_USER_NAME = 'notify-admin'
    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
    AWS_ROUTE53_ZONE = os.getenv("AWS_ROUTE53_ZONE", "Z2OW036USASMAK")
    AWS_SES_REGION = os.getenv("AWS_SES_REGION", "us-east-1")
    AWS_SES_SMTP = os.getenv("AWS_SES_SMTP", "email-smtp.us-east-1.amazonaws.com")
    AWS_SES_ACCESS_KEY = os.getenv('AWS_SES_ACCESS_KEY')
    AWS_SES_SECRET_KEY = os.getenv('AWS_SES_SECRET_KEY')
    CSV_UPLOAD_BUCKET_NAME = os.getenv('CSV_UPLOAD_BUCKET_NAME', 'notification-alpha-canada-ca-csv-upload')
    ASSET_UPLOAD_BUCKET_NAME = os.getenv('ASSET_UPLOAD_BUCKET_NAME', 'notification-alpha-canada-ca-asset-upload')
    ASSET_DOMAIN = os.getenv('ASSET_DOMAIN', 's3.amazonaws.com')
    INVITATION_EXPIRATION_DAYS = 2
    NOTIFY_APP_NAME = 'api'
    SQLALCHEMY_RECORD_QUERIES = False
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_POOL_SIZE = int(os.getenv('SQLALCHEMY_POOL_SIZE', 5))
    SQLALCHEMY_POOL_TIMEOUT = 30
    SQLALCHEMY_POOL_RECYCLE = 300
    SQLALCHEMY_STATEMENT_TIMEOUT = 1200
    PAGE_SIZE = 50
    API_PAGE_SIZE = 250
    TEST_MESSAGE_FILENAME = 'Test message'
    ONE_OFF_MESSAGE_FILENAME = 'Report'
    MAX_VERIFY_CODE_COUNT = 10

    # be careful increasing this size without being sure that we won't see slowness in pysftp
    MAX_LETTER_PDF_ZIP_FILESIZE = 40 * 1024 * 1024  # 40mb
    MAX_LETTER_PDF_COUNT_PER_ZIP = 500

    CHECK_PROXY_HEADER = False

    NOTIFY_SERVICE_ID = 'd6aa2c68-a2d9-4437-ab19-3ae8eb202553'
    NOTIFY_USER_ID = '6af522d0-2915-4e52-83a3-3690455a5fe6'
    INVITATION_EMAIL_TEMPLATE_ID = '4f46df42-f795-4cc4-83bb-65ca312f49cc'
    SMS_CODE_TEMPLATE_ID = '36fb0730-6259-4da1-8a80-c8de22ad4246'
    EMAIL_2FA_TEMPLATE_ID = '299726d2-dba6-42b8-8209-30e1d66ea164'
    NEW_USER_EMAIL_VERIFICATION_TEMPLATE_ID = 'ece42649-22a8-4d06-b87f-d52d5d3f0a27'
    PASSWORD_RESET_TEMPLATE_ID = '474e9242-823b-4f99-813d-ed392e7f1201'
    ALREADY_REGISTERED_EMAIL_TEMPLATE_ID = '0880fbb1-a0c6-46f0-9a8e-36c986381ceb'
    CHANGE_EMAIL_CONFIRMATION_TEMPLATE_ID = 'eb4d9930-87ab-4aef-9bce-786762687884'
    SERVICE_NOW_LIVE_TEMPLATE_ID = '618185c6-3636-49cd-b7d2-6f6f5eb3bdde'
    ORGANISATION_INVITATION_EMAIL_TEMPLATE_ID = '203566f0-d835-47c5-aa06-932439c86573'
    TEAM_MEMBER_EDIT_EMAIL_TEMPLATE_ID = 'c73f1d71-4049-46d5-a647-d013bdeca3f0'
    TEAM_MEMBER_EDIT_MOBILE_TEMPLATE_ID = '8a31520f-4751-4789-8ea1-fe54496725eb'
    REPLY_TO_EMAIL_ADDRESS_VERIFICATION_TEMPLATE_ID = 'a42f1d17-9404-46d5-a647-d013bdfca3e1'
    MOU_SIGNER_RECEIPT_TEMPLATE_ID = '4fd2e43c-309b-4e50-8fb8-1955852d9d71'
    MOU_SIGNED_ON_BEHALF_SIGNER_RECEIPT_TEMPLATE_ID = 'c20206d5-bf03-4002-9a90-37d5032d9e84'
    MOU_SIGNED_ON_BEHALF_ON_BEHALF_RECEIPT_TEMPLATE_ID = '522b6657-5ca5-4368-a294-6b527703bd0b'
    MOU_NOTIFY_TEAM_ALERT_TEMPLATE_ID = 'd0e66c4c-0c50-43f0-94f5-f85b613202d4'
    CONTACT_US_TEMPLATE_ID = '8ea9b7a0-a824-4dd3-a4c3-1f508ed20a69'
    ACCOUNT_CHANGE_TEMPLATE_ID = '5b39e16a-9ff8-487c-9bfb-9e06bdb70f36'
    BRANDING_REQUEST_TEMPLATE_ID = '7d423d9e-e94e-4118-879d-d52f383206ae'
    SMTP_TEMPLATE_ID = '3a4cab41-c47d-4d49-96ba-f4c4fa91d44b'

    BROKER_URL = 'sqs://'
    BROKER_TRANSPORT_OPTIONS = {
        'region': AWS_REGION,
        'polling_interval': 1,  # 1 second
        'visibility_timeout': 310,
        'queue_name_prefix': NOTIFICATION_QUEUE_PREFIX
    }
    CELERY_ENABLE_UTC = True
    CELERY_TIMEZONE = os.getenv("TIMEZONE", "America/Toronto")
    CELERY_ACCEPT_CONTENT = ['json']
    CELERY_TASK_SERIALIZER = 'json'
    CELERY_IMPORTS = (
        'app.celery.tasks',
        'app.celery.scheduled_tasks',
        'app.celery.reporting_tasks',
        'app.celery.nightly_tasks',
    )
    CELERYBEAT_SCHEDULE = {
        # app/celery/scheduled_tasks.py
        'run-scheduled-jobs': {
            'task': 'run-scheduled-jobs',
            'schedule': crontab(minute=1),
            'options': {'queue': QueueNames.PERIODIC}
        },
        'delete-verify-codes': {
            'task': 'delete-verify-codes',
            'schedule': timedelta(minutes=63),
            'options': {'queue': QueueNames.PERIODIC}
        },
        'delete-invitations': {
            'task': 'delete-invitations',
            'schedule': timedelta(minutes=66),
            'options': {'queue': QueueNames.PERIODIC}
        },
        'switch-current-sms-provider-on-slow-delivery': {
            'task': 'switch-current-sms-provider-on-slow-delivery',
            'schedule': crontab(),  # Every minute
            'options': {'queue': QueueNames.PERIODIC}
        },
        'check-job-status': {
            'task': 'check-job-status',
            'schedule': crontab(),
            'options': {'queue': QueueNames.PERIODIC}
        },
        'replay-created-notifications': {
            'task': 'replay-created-notifications',
            'schedule': crontab(minute='0, 15, 30, 45'),
            'options': {'queue': QueueNames.PERIODIC}
        },
        # app/celery/nightly_tasks.py
        'timeout-sending-notifications': {
            'task': 'timeout-sending-notifications',
            'schedule': crontab(hour=0, minute=5),
            'options': {'queue': QueueNames.PERIODIC}
        },
        'create-nightly-billing': {
            'task': 'create-nightly-billing',
            'schedule': crontab(hour=0, minute=15),
            'options': {'queue': QueueNames.REPORTING}
        },
        'create-nightly-notification-status': {
            'task': 'create-nightly-notification-status',
            'schedule': crontab(hour=0, minute=30),  # after 'timeout-sending-notifications'
            'options': {'queue': QueueNames.REPORTING}
        },
        'delete-sms-notifications': {
            'task': 'delete-sms-notifications',
            'schedule': crontab(hour=4, minute=15),  # after 'create-nightly-notification-status'
            'options': {'queue': QueueNames.PERIODIC}
        },
        'delete-email-notifications': {
            'task': 'delete-email-notifications',
            'schedule': crontab(hour=4, minute=30),  # after 'create-nightly-notification-status'
            'options': {'queue': QueueNames.PERIODIC}
        },
        'delete-letter-notifications': {
            'task': 'delete-letter-notifications',
            'schedule': crontab(hour=4, minute=45),  # after 'create-nightly-notification-status'
            'options': {'queue': QueueNames.PERIODIC}
        },
        'delete-inbound-sms': {
            'task': 'delete-inbound-sms',
            'schedule': crontab(hour=1, minute=40),
            'options': {'queue': QueueNames.PERIODIC}
        },

        'send-daily-performance-platform-stats': {
            'task': 'send-daily-performance-platform-stats',
            'schedule': crontab(hour=2, minute=0),
            'options': {'queue': QueueNames.PERIODIC}
        },
        'remove_transformed_dvla_files': {
            'task': 'remove_transformed_dvla_files',
            'schedule': crontab(hour=3, minute=40),
            'options': {'queue': QueueNames.PERIODIC}
        },
        'remove_sms_email_jobs': {
            'task': 'remove_sms_email_jobs',
            'schedule': crontab(hour=4, minute=0),
            'options': {'queue': QueueNames.PERIODIC},
        },
        # 'remove_letter_jobs': {
        # 'task': 'remove_letter_jobs',
        # 'schedule': crontab(hour=4, minute=20),
        #  since we mark jobs as archived
        # 'options': {'queue': QueueNames.PERIODIC},
        # },
        # 'check-templated-letter-state': {
        # 'task': 'check-templated-letter-state',
        # 'schedule': crontab(day_of_week='mon-fri', hour=9, minute=0),
        # 'options': {'queue': QueueNames.PERIODIC}
        # },
        # 'check-precompiled-letter-state': {
        # 'task': 'check-precompiled-letter-state',
        # 'schedule': crontab(day_of_week='mon-fri', hour='9,15', minute=0),
        # 'options': {'queue': QueueNames.PERIODIC}
        # },
        # 'raise-alert-if-letter-notifications-still-sending': {
        # 'task': 'raise-alert-if-letter-notifications-still-sending',
        # 'schedule': crontab(hour=16, minute=30),
        # 'options': {'queue': QueueNames.PERIODIC}
        # },
        # The collate-letter-pdf does assume it is called in an hour that BST does not make a
        # difference to the truncate date which translates to the filename to process
        # 'collate-letter-pdfs-for-day': {
        # 'task': 'collate-letter-pdfs-for-day',
        # 'schedule': crontab(hour=17, minute=50),
        # 'options': {'queue': QueueNames.PERIODIC}
        # },
        # 'raise-alert-if-no-letter-ack-file': {
        # 'task': 'raise-alert-if-no-letter-ack-file',
        # 'schedule': crontab(hour=23, minute=00),
        # 'options': {'queue': QueueNames.PERIODIC}
        # },
    }
    CELERY_QUEUES = []

    FROM_NUMBER = 'development'

    STATSD_HOST = os.getenv('STATSD_HOST')
    STATSD_PORT = 8125
    STATSD_ENABLED = bool(STATSD_HOST)

    SENDING_NOTIFICATIONS_TIMEOUT_PERIOD = 259200  # 3 days

    SIMULATED_EMAIL_ADDRESSES = (
        'simulate-delivered@notifications.service.gov.uk',
        'simulate-delivered-2@notifications.service.gov.uk',
        'simulate-delivered-3@notifications.service.gov.uk',
    )

    SIMULATED_SMS_NUMBERS = ('+16132532222', '+16132532223', '+16132532224')

    DVLA_BUCKETS = {
        'job': '{}-dvla-file-per-job'.format(os.getenv('NOTIFY_ENVIRONMENT', 'development')),
        'notification': '{}-dvla-letter-api-files'.format(os.getenv('NOTIFY_ENVIRONMENT', 'development'))
    }

    FREE_SMS_TIER_FRAGMENT_COUNT = 250000

    SMS_INBOUND_WHITELIST = json.loads(os.getenv('SMS_INBOUND_WHITELIST', '[]'))
    FIRETEXT_INBOUND_SMS_AUTH = json.loads(os.getenv('FIRETEXT_INBOUND_SMS_AUTH', '[]'))
    MMG_INBOUND_SMS_AUTH = json.loads(os.getenv('MMG_INBOUND_SMS_AUTH', '[]'))
    MMG_INBOUND_SMS_USERNAME = json.loads(os.getenv('MMG_INBOUND_SMS_USERNAME', '[]'))

    ROUTE_SECRET_KEY_1 = os.getenv('ROUTE_SECRET_KEY_1', '')
    ROUTE_SECRET_KEY_2 = os.getenv('ROUTE_SECRET_KEY_2', '')

    # Format is as follows:
    # {"dataset_1": "token_1", ...}
    PERFORMANCE_PLATFORM_ENDPOINTS = json.loads(os.getenv('PERFORMANCE_PLATFORM_ENDPOINTS', '{}'))

    TEMPLATE_PREVIEW_API_HOST = os.getenv('TEMPLATE_PREVIEW_API_HOST', 'http://localhost:6013')
    TEMPLATE_PREVIEW_API_KEY = os.getenv('TEMPLATE_PREVIEW_API_KEY', 'my-secret-key')

    DOCUMENT_DOWNLOAD_API_HOST = os.getenv('DOCUMENT_DOWNLOAD_API_HOST', 'http://localhost:7000')
    DOCUMENT_DOWNLOAD_API_KEY = os.getenv('DOCUMENT_DOWNLOAD_API_KEY', 'auth-token')

    MMG_URL = os.getenv("MMG_URL", "https://api.mmg.co.uk/json/api.php")
    FIRETEXT_URL = os.getenv("FIRETEXT_URL", "https://www.firetext.co.uk/api/sendsms/json")

    AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
    NOTIFY_LOG_PATH = ''

    FIDO2_SERVER = Fido2Server(
        RelyingParty(os.getenv('FIDO2_DOMAIN', 'localhost'), 'Notification'),
        verify_origin=lambda x: True)


######################
# Config overrides ###
######################

class Development(Config):
    DEBUG = True
    SQLALCHEMY_ECHO = False

    # CSV_UPLOAD_BUCKET_NAME = 'development-notifications-csv-upload'
    TEST_LETTERS_BUCKET_NAME = 'development-test-letters'
    DVLA_RESPONSE_BUCKET_NAME = 'notify.tools-ftp'
    LETTERS_PDF_BUCKET_NAME = 'development-letters-pdf'
    LETTERS_SCAN_BUCKET_NAME = 'development-letters-scan'
    INVALID_PDF_BUCKET_NAME = 'development-letters-invalid-pdf'
    TRANSIENT_UPLOADED_LETTERS = 'development-transient-uploaded-letters'

    ADMIN_CLIENT_SECRET = os.getenv('ADMIN_CLIENT_SECRET', 'dev-notify-secret-key')
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-notify-secret-key')
    DANGEROUS_SALT = os.getenv('DANGEROUS_SALT', 'dev-notify-salt ')

    MMG_INBOUND_SMS_AUTH = ['testkey']
    MMG_INBOUND_SMS_USERNAME = ['username']

    NOTIFY_ENVIRONMENT = 'development'
    NOTIFICATION_QUEUE_PREFIX = os.getenv("NOTIFICATION_QUEUE_PREFIX", "notification-canada-ca")
    NOTIFY_EMAIL_DOMAIN = os.getenv("NOTIFY_EMAIL_DOMAIN", "notification.alpha.canada.ca")

    SQLALCHEMY_DATABASE_URI = os.getenv("SQLALCHEMY_DATABASE_URI", 'postgresql://postgres@localhost/notification_api')
    REDIS_URL = 'redis://localhost:6379/0'

    ANTIVIRUS_ENABLED = os.getenv('ANTIVIRUS_ENABLED') == '1'

    for queue in QueueNames.all_queues():
        Config.CELERY_QUEUES.append(
            Queue(queue, Exchange('default'), routing_key=queue)
        )

    API_HOST_NAME = "http://localhost:6011"
    API_RATE_LIMIT_ENABLED = True


class Test(Development):
    NOTIFY_EMAIL_DOMAIN = os.getenv("NOTIFY_EMAIL_DOMAIN", "notification.alpha.canada.ca")
    FROM_NUMBER = 'testing'
    NOTIFY_ENVIRONMENT = 'test'
    TESTING = True

    # CSV_UPLOAD_BUCKET_NAME = 'test-notifications-csv-upload'
    TEST_LETTERS_BUCKET_NAME = 'test-test-letters'
    DVLA_RESPONSE_BUCKET_NAME = 'test.notify.com-ftp'
    LETTERS_PDF_BUCKET_NAME = 'test-letters-pdf'
    LETTERS_SCAN_BUCKET_NAME = 'test-letters-scan'
    INVALID_PDF_BUCKET_NAME = 'test-letters-invalid-pdf'
    TRANSIENT_UPLOADED_LETTERS = 'test-transient-uploaded-letters'

    # this is overriden in jenkins and on cloudfoundry
    SQLALCHEMY_DATABASE_URI = os.getenv(
        'SQLALCHEMY_DATABASE_URI',
        'postgresql://postgres@localhost/test_notification_api'
    )

    BROKER_URL = 'you-forgot-to-mock-celery-in-your-tests://'

    ANTIVIRUS_ENABLED = True

    for queue in QueueNames.all_queues():
        Config.CELERY_QUEUES.append(
            Queue(queue, Exchange('default'), routing_key=queue)
        )

    API_RATE_LIMIT_ENABLED = True
    API_HOST_NAME = "http://localhost:6011"

    SMS_INBOUND_WHITELIST = ['203.0.113.195']
    FIRETEXT_INBOUND_SMS_AUTH = ['testkey']
    TEMPLATE_PREVIEW_API_HOST = 'http://localhost:9999'

    MMG_URL = 'https://example.com/mmg'
    FIRETEXT_URL = 'https://example.com/firetext'


class Production(Config):
    NOTIFY_EMAIL_DOMAIN = os.getenv("NOTIFY_EMAIL_DOMAIN", "notification.alpha.canada.ca")
    NOTIFY_ENVIRONMENT = 'production'
    # CSV_UPLOAD_BUCKET_NAME = 'live-notifications-csv-upload'
    TEST_LETTERS_BUCKET_NAME = 'production-test-letters'
    DVLA_RESPONSE_BUCKET_NAME = 'notifications.service.gov.uk-ftp'
    LETTERS_PDF_BUCKET_NAME = 'production-letters-pdf'
    LETTERS_SCAN_BUCKET_NAME = 'production-letters-scan'
    INVALID_PDF_BUCKET_NAME = 'production-letters-invalid-pdf'
    TRANSIENT_UPLOADED_LETTERS = 'production-transient-uploaded-letters'
    FROM_NUMBER = 'CANADA.CA'
    PERFORMANCE_PLATFORM_ENABLED = False
    API_RATE_LIMIT_ENABLED = True
    CHECK_PROXY_HEADER = False
    CRONITOR_ENABLED = False


configs = {
    'development': Development,
    'test': Test,
    'production': Production,
}
