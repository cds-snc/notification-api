import pytest
from app.celery.error_registry import CeleryErrorCategory, classify_error
from sqlalchemy.exc import IntegrityError, OperationalError


class TestClassifyError:
    def test_throttling_by_class_name(self):
        """Botocore throttling exceptions are classified correctly."""

        class ThrottlingException(Exception):
            pass

        exc = ThrottlingException("Rate Exceeded")
        assert classify_error(exc) == CeleryErrorCategory.THROTTLING

    def test_throttling_by_message(self):
        """Generic exceptions with throttling messages are classified."""
        exc = Exception("An error occurred (ThrottlingException): Rate Exceeded")
        assert classify_error(exc) == CeleryErrorCategory.THROTTLING

    def test_duplicate_record_integrity_error(self):
        """SQLAlchemy IntegrityError is classified as duplicate."""
        exc = IntegrityError("INSERT", {}, Exception("duplicate key value"))
        assert classify_error(exc) == CeleryErrorCategory.DUPLICATE_RECORD

    def test_chained_exception_finds_root_cause(self):
        """Walks __cause__ chain to find the root throttling error."""

        class ThrottlingException(Exception):
            pass

        root = ThrottlingException("Rate Exceeded")
        wrapper = Exception("Task failed")
        wrapper.__cause__ = root
        assert classify_error(wrapper) == CeleryErrorCategory.THROTTLING

    def test_chained_exception_via_context(self):
        """Walks __context__ chain when __cause__ is None."""

        class ThrottlingException(Exception):
            pass

        root = ThrottlingException("Rate Exceeded")
        wrapper = Exception("Task failed")
        wrapper.__context__ = root
        assert classify_error(wrapper) == CeleryErrorCategory.THROTTLING

    def test_duplicate_record_already_exists_message(self):
        """Duplicate records caught by 'already exists' message."""
        exc = Exception("Key already exists in database")
        assert classify_error(exc) == CeleryErrorCategory.DUPLICATE_RECORD

    def test_duplicate_record_unique_violation(self):
        """PostgreSQL UniqueViolation exception is classified as duplicate."""

        class UniqueViolation(Exception):
            pass

        exc = UniqueViolation("duplicate key value violates unique constraint")
        assert classify_error(exc) == CeleryErrorCategory.DUPLICATE_RECORD

    def test_job_incomplete_error(self):
        """JobIncompleteError is classified correctly."""

        class JobIncompleteError(Exception):
            pass

        exc = JobIncompleteError("Job was interrupted during deploy")
        assert classify_error(exc) == CeleryErrorCategory.JOB_INCOMPLETE

    def test_notification_not_found_by_exception(self):
        """NoResultFound exception is classified as notification not found."""

        class NoResultFound(Exception):
            pass

        exc = NoResultFound("No notification found for this ID")
        assert classify_error(exc) == CeleryErrorCategory.NOTIFICATION_NOT_FOUND

    def test_notification_not_found_by_message(self):
        """Messages about SES references not found are classified correctly."""
        exc = Exception("notifications not found for SES references: [id-123]")
        assert classify_error(exc) == CeleryErrorCategory.NOTIFICATION_NOT_FOUND

    def test_shutdown_error(self):
        """SIGKILL messages are classified as shutdown."""
        exc = Exception("Process received SIGKILL during graceful shutdown")
        assert classify_error(exc) == CeleryErrorCategory.SHUTDOWN

    def test_timeout_error(self):
        """Timeout-related messages are classified correctly."""
        exc = Exception("timeout-sending-notifications: Task exceeded time limit")
        assert classify_error(exc) == CeleryErrorCategory.TIMEOUT

    def test_xray_error(self):
        """X-Ray related errors are classified correctly."""
        exc = Exception("Error in xray-celery segment creation")
        assert classify_error(exc) == CeleryErrorCategory.XRAY

    def test_unknown_error(self):
        exc = Exception("Something completely unexpected")
        assert classify_error(exc) == CeleryErrorCategory.UNKNOWN

    def test_none_exception(self):
        assert classify_error(None) == CeleryErrorCategory.UNKNOWN

    def test_classification_order(self):
        """First match wins: class name patterns take precedence over message substrings."""

        class ThrottlingException(Exception):
            pass

        exc = ThrottlingException("This message contains 'already exists' but should be throttling")
        assert classify_error(exc) == CeleryErrorCategory.THROTTLING

    def test_classification_order_between_messages(self):
        """First match wins: message substrings take precedence over other message substrings."""

        exc = Exception("This message contains 'Throttling' but also 'already exists'")
        assert classify_error(exc) == CeleryErrorCategory.DUPLICATE_RECORD

