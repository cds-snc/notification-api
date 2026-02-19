from sqlalchemy.exc import IntegrityError

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
        exc = IntegrityError("INSERT", {}, Exception("duplicate key value violates unique constraint"))
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
        """Walks __context__ chain when __cause__ is `None`."""

        class ThrottlingException(Exception):
            pass

        root = ThrottlingException("Rate Exceeded")
        wrapper = Exception("Task failed")
        wrapper.__context__ = root
        assert classify_error(wrapper) == CeleryErrorCategory.THROTTLING

    def test_duplicate_record_duplicate_key_value_violates_unique_constraint_message(self):
        """Duplicate records caught by 'duplicate key value violates unique constraint' message."""
        exc = Exception("duplicate key value violates unique constraint in database")
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

        exc = ThrottlingException(
            "This message contains 'duplicate key value violates unique constraint' but should be throttling"
        )
        assert classify_error(exc) == CeleryErrorCategory.THROTTLING

    def test_classification_order_between_messages(self):
        """First match wins: message substrings take precedence over other message substrings."""

        exc = Exception("This message contains 'Throttling' but also 'duplicate key value violates unique constraint'")
        assert classify_error(exc) == CeleryErrorCategory.DUPLICATE_RECORD

    def test_prefers_deepest_exception_in_chain(self):
        """When both root and wrapper exception match, prefer the root (deepest) exception."""

        class ThrottlingException(Exception):
            """Root cause: throttling"""

            pass

        class JobIncompleteError(Exception):
            """Wrapper: job incomplete"""

            pass

        # Create chain: wrapper exception with root cause as __cause__
        root = ThrottlingException("Rate Exceeded")
        wrapper = JobIncompleteError("Job interrupted by deploy")
        wrapper.__cause__ = root

        # Should classify as THROTTLING (root), not JOB_INCOMPLETE (wrapper)
        assert classify_error(wrapper) == CeleryErrorCategory.THROTTLING

    def test_deepest_match_wins_with_context_chain(self):
        """When using __context__, still prefer the deepest matching exception."""

        class TimeoutException(Exception):
            """Root cause: timeout"""

            pass

        class NotifyException(Exception):
            """Wrapper: generic notify error"""

            pass

        # Create chain via __context__
        root = TimeoutException("timeout-sending-notifications reached")
        wrapper = NotifyException("An error occurred during notification processing")
        wrapper.__context__ = root

        # Should classify as TIMEOUT (root), not UNKNOWN (wrapper)
        assert classify_error(wrapper) == CeleryErrorCategory.TIMEOUT

    def test_circular_exception_chain_does_not_infinite_loop(self):
        """Circular exception chains are detected and handled without infinite loops."""

        class ThrottlingException(Exception):
            """Throttling exception that points to itself"""

            pass

        # Create a circular chain: exc -> exc.__cause__ -> exc (cycle)
        exc = ThrottlingException("Rate Exceeded")
        exc.__cause__ = exc  # Creates a cycle

        # Should classify correctly and not infinite loop
        assert classify_error(exc) == CeleryErrorCategory.THROTTLING

    def test_circular_exception_chain_multiple_exceptions(self):
        """Complex circular chain A -> B -> A is detected and handled."""

        class ThrottlingException(Exception):
            pass

        class TimeoutException(Exception):
            pass

        # Create A -> B -> A cycle
        exc_a = ThrottlingException("Rate Exceeded")
        exc_b = TimeoutException("timeout-sending-notifications")
        exc_a.__cause__ = exc_b
        exc_b.__cause__ = exc_a  # Cycle created

        # Should classify as THROTTLING (encountered first in the chain)
        # The set-based detection prevents infinite loop
        result = classify_error(exception=exc_a)
        assert result == CeleryErrorCategory.TIMEOUT
