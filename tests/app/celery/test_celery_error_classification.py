from unittest.mock import MagicMock, patch

from sqlalchemy.exc import IntegrityError

from app.celery.celery import classify_celery_task_failure, classify_celery_task_retry
from app.celery.error_registry import CeleryErrorCategory, classify_error


class TestClassifyError:
    def test_throttling_by_class_name(self):
        """Botocore throttling exceptions are classified correctly."""

        class ThrottlingException(Exception):
            pass

        exc = ThrottlingException("Rate Exceeded")
        category, root_exc = classify_error(exc)
        assert category == CeleryErrorCategory.THROTTLING
        assert root_exc is exc  # Should return the original exception as root

    def test_throttling_by_message(self):
        """Generic exceptions with throttling messages are classified."""
        exc = Exception("An error occurred (ThrottlingException): Rate Exceeded")
        category, root_exc = classify_error(exc)
        assert category == CeleryErrorCategory.THROTTLING
        assert root_exc is exc  # Should return the original exception as root

    def test_duplicate_record_integrity_error(self):
        """SQLAlchemy IntegrityError is classified as duplicate."""
        exc = IntegrityError("INSERT", {}, Exception("duplicate key value violates unique constraint"))
        category, root_exc = classify_error(exc)
        assert category == CeleryErrorCategory.DUPLICATE_RECORD
        assert root_exc is exc  # Should return the original exception as root

    def test_chained_exception_finds_root_cause(self):
        """Walks __cause__ chain to find the root throttling error."""

        class ThrottlingException(Exception):
            pass

        root = ThrottlingException("Rate Exceeded")
        wrapper = Exception("Task failed")
        wrapper.__cause__ = root
        category, root_exc = classify_error(wrapper)
        assert category == CeleryErrorCategory.THROTTLING
        assert root_exc is root  # Should return the root exception

    def test_chained_exception_via_context(self):
        """Walks __context__ chain when __cause__ is `None`."""

        class ThrottlingException(Exception):
            pass

        root = ThrottlingException("Rate Exceeded")
        wrapper = Exception("Task failed")
        wrapper.__context__ = root
        category, root_exc = classify_error(wrapper)
        assert category == CeleryErrorCategory.THROTTLING
        assert root_exc is root  # Should return the root exception

    def test_duplicate_record_duplicate_key_value_violates_unique_constraint_message(self):
        """Duplicate records caught by 'duplicate key value violates unique constraint' message."""
        exc = Exception("duplicate key value violates unique constraint in database")
        category, root_exc = classify_error(exc)
        assert category == CeleryErrorCategory.DUPLICATE_RECORD
        assert root_exc is exc  # Should return the original exception as root

    def test_duplicate_record_unique_violation(self):
        """PostgreSQL UniqueViolation exception is classified as duplicate."""

        class UniqueViolation(Exception):
            pass

        exc = UniqueViolation("duplicate key value violates unique constraint")
        category, root_exc = classify_error(exc)
        assert category == CeleryErrorCategory.DUPLICATE_RECORD
        assert root_exc is exc  # Should return the original exception as root

    def test_job_incomplete_error(self):
        """JobIncompleteError is classified correctly."""

        class JobIncompleteError(Exception):
            pass

        exc = JobIncompleteError("Job was interrupted during deploy")
        category, root_exc = classify_error(exc)
        assert category == CeleryErrorCategory.JOB_INCOMPLETE
        assert root_exc is exc  # Should return the original exception as root

    def test_notification_not_found_by_exception(self):
        """NoResultFound exception is classified as notification not found."""

        class NoResultFound(Exception):
            pass

        exc = NoResultFound("No notification found for this ID")
        category, root_exc = classify_error(exc)
        assert category == CeleryErrorCategory.NOTIFICATION_NOT_FOUND
        assert root_exc is exc  # Should return the original exception as root

    def test_notification_not_found_by_message(self):
        """Messages about SES references not found are classified correctly."""
        exc = Exception("notifications not found for SES references: [id-123]")
        category, root_exc = classify_error(exc)
        assert category == CeleryErrorCategory.NOTIFICATION_NOT_FOUND
        assert root_exc is exc  # Should return the original exception as root

    def test_shutdown_error(self):
        """SIGKILL messages are classified as shutdown."""
        exc = Exception("Process received SIGKILL during graceful shutdown")
        category, root_exc = classify_error(exc)
        assert category == CeleryErrorCategory.SHUTDOWN
        assert root_exc is exc  # Should return the original exception as root

    def test_timeout_error(self):
        """Timeout-related messages are classified correctly."""
        exc = Exception("timeout-sending-notifications: Task exceeded time limit")
        category, root_exc = classify_error(exc)
        assert category == CeleryErrorCategory.TIMEOUT
        assert root_exc is exc  # Should return the original exception as root

    def test_xray_error(self):
        """X-Ray related errors are classified correctly."""
        exc = Exception("Error in xray-celery segment creation")
        category, root_exc = classify_error(exc)
        assert category == CeleryErrorCategory.XRAY
        assert root_exc is exc  # Should return the original exception as root

    def test_unknown_error(self):
        exc = Exception("Something completely unexpected")
        category, root_exc = classify_error(exc)
        assert category == CeleryErrorCategory.UNKNOWN
        assert root_exc is exc  # Should return the original exception as root

    def test_none_exception(self):
        category, root_exc = classify_error(None)
        assert category == CeleryErrorCategory.UNKNOWN
        assert root_exc is None

    def test_classification_order(self):
        """First match wins: class name patterns take precedence over message substrings."""

        class ThrottlingException(Exception):
            pass

        exc = ThrottlingException(
            "This message contains 'duplicate key value violates unique constraint' but should be throttling"
        )
        category, root_exc = classify_error(exception=exc)
        assert category == CeleryErrorCategory.THROTTLING
        assert root_exc is exc  # Should return the original exception as root

    def test_classification_order_between_messages(self):
        """First match wins: message substrings take precedence over other message substrings."""

        exc = Exception("This message contains 'Throttling' but also 'duplicate key value violates unique constraint'")
        category, root_exc = classify_error(exc)
        assert category == CeleryErrorCategory.DUPLICATE_RECORD
        assert root_exc is exc  # Should return the original exception as root

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
        category, root_exc = classify_error(wrapper)
        assert category == CeleryErrorCategory.THROTTLING
        assert root_exc is root  # Should return the root exception as root

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
        category, root_exc = classify_error(wrapper)
        assert category == CeleryErrorCategory.TIMEOUT
        assert root_exc is root  # Should return the root exception as root

    def test_circular_exception_chain_does_not_infinite_loop(self):
        """Circular exception chains are detected and handled without infinite loops."""

        class ThrottlingException(Exception):
            """Throttling exception that points to itself"""

            pass

        # Create a circular chain: exc -> exc.__cause__ -> exc (cycle)
        exc = ThrottlingException("Rate Exceeded")
        exc.__cause__ = exc  # Creates a cycle

        # Should classify correctly and not infinite loop
        category, root_exc = classify_error(exc)
        assert category == CeleryErrorCategory.THROTTLING
        assert root_exc is exc  # Should return the original exception as root

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

        # Should classify as TIMEOUT (deepest/root in the chain), not THROTTLING encountered earlier
        # The set-based detection prevents infinite loop while still finding the deepest matching exception
        category, root_exc = classify_error(exception=exc_a)
        assert category == CeleryErrorCategory.TIMEOUT
        assert root_exc is exc_b  # Should return the last exception before cycle detected

    def test_task_retry_by_celery_exception(self):
        """Celery Retry exception is classified as TASK_RETRY."""
        from celery.exceptions import Retry

        exc = Retry("Retry in 300s")
        category, root_exc = classify_error(exc)
        assert category == CeleryErrorCategory.TASK_RETRY
        assert root_exc is exc  # Should return the original exception as root

    def test_task_retry_by_message(self):
        """Generic exceptions with retry message are classified as TASK_RETRY."""
        exc = Exception("Retry in 300s: task will be retried")
        category, root_exc = classify_error(exc)
        assert category == CeleryErrorCategory.TASK_RETRY
        assert root_exc is exc  # Should return the original exception as root


class TestCelerySignalHandlers:
    def test_task_retry_classifies_throttling(self, notify_api):
        """task_retry signal handler classifies and logs throttling errors."""

        class ThrottlingException(Exception):
            pass

        sender = MagicMock()
        sender.name = "deliver_email"
        request = MagicMock()
        request.id = "abc-123"

        with patch.object(notify_api.logger, "warning") as mock_warning:
            classify_celery_task_retry(
                sender=sender,
                reason=ThrottlingException("Rate Exceeded"),
                request=request,
            )

            mock_warning.assert_called_once()
            log_message = mock_warning.call_args[0][0] % mock_warning.call_args[0][1:]
            assert "CELERY_KNOWN_ERROR::THROTTLING" in log_message
            assert "deliver_email" in log_message
            assert "abc-123" in log_message

    def test_task_retry_unknown_when_reason_is_not_exception(self, notify_api):
        """task_retry classifies as UNKNOWN when reason is not an Exception."""
        sender = MagicMock()
        sender.name = "deliver_sms"
        request = MagicMock()
        request.id = "def-456"

        with patch.object(notify_api.logger, "warning") as mock_warning:
            classify_celery_task_retry(
                sender=sender,
                reason="some string reason",
                request=request,
            )

            mock_warning.assert_called_once()
            log_message = mock_warning.call_args[0][0] % mock_warning.call_args[0][1:]
            assert "CELERY_UNKNOWN_ERROR" in log_message

    def test_task_retry_handles_missing_sender_and_request(self, notify_api):
        """task_retry handles None sender and request gracefully."""
        with patch.object(notify_api.logger, "warning") as mock_warning:
            classify_celery_task_retry(
                sender=None,
                reason=Exception("some error"),
                request=None,
            )

            mock_warning.assert_called_once()
            log_message = mock_warning.call_args[0][0] % mock_warning.call_args[0][1:]
            assert "task_name=unknown" in log_message
            assert "task_id=unknown" in log_message

    def test_task_failure_classifies_throttling(self, notify_api):
        """task_failure signal handler classifies and logs throttling errors."""

        class ThrottlingException(Exception):
            pass

        sender = MagicMock()
        sender.name = "deliver_email"

        with patch.object(notify_api.logger, "warning") as mock_warning:
            classify_celery_task_failure(
                sender=sender,
                task_id="abc-123",
                exception=ThrottlingException("Rate Exceeded"),
            )

            mock_warning.assert_called_once()
            log_message = mock_warning.call_args[0][0] % mock_warning.call_args[0][1:]
            assert "CELERY_KNOWN_ERROR::THROTTLING" in log_message
            assert "deliver_email" in log_message
            assert "abc-123" in log_message

    def test_task_failure_classifies_unknown(self, notify_api):
        """task_failure classifies unrecognized exceptions as UNKNOWN."""
        sender = MagicMock()
        sender.name = "deliver_sms"

        with patch.object(notify_api.logger, "warning") as mock_warning:
            classify_celery_task_failure(
                sender=sender,
                task_id="ghi-789",
                exception=Exception("Something unexpected"),
            )

            mock_warning.assert_called_once()
            log_message = mock_warning.call_args[0][0] % mock_warning.call_args[0][1:]
            assert "CELERY_UNKNOWN_ERROR" in log_message

    def test_task_failure_handles_missing_sender(self, notify_api):
        """task_failure handles None sender gracefully."""
        with patch.object(notify_api.logger, "warning") as mock_warning:
            classify_celery_task_failure(
                sender=None,
                task_id="jkl-012",
                exception=Exception("error"),
            )

            mock_warning.assert_called_once()
            log_message = mock_warning.call_args[0][0] % mock_warning.call_args[0][1:]
            assert "task_name=unknown" in log_message
