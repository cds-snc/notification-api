from notifications_utils.statsd_decorators import statsd

from app import notify_celery
from app.cronitor import cronitor


@notify_celery.task(bind=True, name="create-letters-pdf", max_retries=15, default_retry_delay=300)
@statsd(namespace="tasks")
def create_letters_pdf(self, notification_id):
    pass


def get_letters_pdf(template, contact_block, filename, values):
    pass


@notify_celery.task(name="collate-letter-pdfs-for-day")
@cronitor("collate-letter-pdfs-for-day")
def collate_letter_pdfs_for_day(date=None):
    pass


def group_letters(letter_pdfs):
    pass


def letter_in_created_state(filename):
    pass


@notify_celery.task(bind=True, name="process-virus-scan-passed", max_retries=15, default_retry_delay=300)
def process_virus_scan_passed(self, filename):
    pass


@notify_celery.task(name="process-virus-scan-failed")
def process_virus_scan_failed(filename):
    pass


@notify_celery.task(name="process-virus-scan-error")
def process_virus_scan_error(filename):
    pass


def update_letter_pdf_status(reference, status, billable_units):
    pass


def replay_letters_in_error(filename=None):
    pass
