from enum import Enum

from app.models import SECOND_CLASS


class ScanErrorType(Enum):
    ERROR = 1
    FAILURE = 2


LETTERS_PDF_FILE_LOCATION_STRUCTURE = "{folder}NOTIFY.{reference}.{duplex}.{letter_class}.{colour}.{crown}.{date}.pdf"

PRECOMPILED_BUCKET_PREFIX = "{folder}NOTIFY.{reference}"


def get_folder_name(_now, is_test_or_scan_letter=False):
    pass


def get_letter_pdf_filename(reference, crown, is_scan_letter=False, postage=SECOND_CLASS):
    pass


def get_bucket_name_and_prefix_for_notification(notification):
    pass


def get_reference_from_filename(filename):
    pass


def upload_letter_pdf(notification, pdf_data, precompiled=False):
    pass


def move_failed_pdf(source_filename, scan_error_type):
    pass


def copy_redaction_failed_pdf(source_filename):
    pass


def move_error_pdf_to_scan_bucket(source_filename):
    pass


def move_scan_to_invalid_pdf_bucket(source_filename):
    pass


def move_uploaded_pdf_to_letters_bucket(source_filename, upload_filename):
    pass


def get_file_names_from_error_bucket():
    pass


def get_letter_pdf(notification):
    pass


def _move_s3_object(source_bucket, source_filename, target_bucket, target_filename):
    pass


def _copy_s3_object(source_bucket, source_filename, target_bucket, target_filename):
    pass


def letter_print_day(created_at):
    pass


def get_page_count(pdf):
    pass
