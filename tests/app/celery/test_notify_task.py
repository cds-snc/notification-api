import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from app.celery.error_registry import CeleryErrorCategory, classify_error


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

    def test_unknown_error(self):
        exc = Exception("Something completely unexpected")
        assert classify_error(exc) == CeleryErrorCategory.UNKNOWN

    def test_none_exception(self):
        assert classify_error(None) == CeleryErrorCategory.UNKNOWN
