from celery.signals import (
    task_prerun,
    task_postrun,
    task_internal_error,
    task_revoked,
    task_unknown,
    task_rejected,
)
from unittest.mock import MagicMock


def test_task_prerun_logging(mocker, notify_api):
    """Test logging for celery task_prerun signal."""
    mock_logger = mocker.patch('app.celery.celery.current_app.logger.debug')

    task = MagicMock(name='dummy_task')
    task_id = '12345'

    task_prerun.send(sender=None, task_id=task_id, task=task)

    mock_logger.assert_called_once_with('celery task_prerun task_id: %s | task_name: %s', task_id, task.name)


def test_task_postrun_logging(mocker, notify_api):
    """Test logging for celery task_postrun signal."""
    mock_logger = mocker.patch('app.celery.celery.current_app.logger.debug')

    task = MagicMock(name='dummy_task')
    task_id = '12345'

    task_postrun.send(sender=None, task_id=task_id, task=task)

    mock_logger.assert_called_once_with('celery task_postrun task_id: %s | task_name: %s', task_id, task.name)


def test_task_internal_error_logging(mocker, notify_api):
    """Test logging for celery task_internal_error signal."""
    mock_logger = mocker.patch('app.celery.celery.current_app.logger.exception')

    task_id = '12345'
    request = MagicMock(task_name='dummy_task')
    exception = ValueError('Test error message')

    task_internal_error.send(sender=None, task_id=task_id, request=request, exception=exception)

    mock_logger.assert_called_once_with(
        'celery task_internal_error task_id: %s | task_name: %s | exception: %s',
        task_id,
        request.task_name,
        exception,
    )


def test_task_revoked_logging(mocker, notify_api):
    """Test logging for celery task_revoked signal."""
    mock_logger = mocker.patch('app.celery.celery.current_app.logger.error')

    request = MagicMock(task='dummy_task', id='12345')
    terminated = True
    expired = False
    signum = 9

    task_revoked.send(sender=None, request=request, terminated=terminated, signum=signum, expired=expired)

    mock_logger.assert_called_once_with(
        'celery task_revoked request_task: %s | request_id: %s | terminated: %s | signum: %s | expired: %s',
        request.task,
        request.id,
        terminated,
        signum,
        expired,
    )


def test_task_unknown_logging(mocker, notify_api):
    """Test logging for celery task_unknown signal."""
    mock_logger = mocker.patch('app.celery.celery.current_app.logger.exception')

    message = 'Unknown task received'
    exc = Exception('UnknownTaskError')
    name = 'unknown_name'
    id = '12345'

    task_unknown.send(sender=None, message=message, exc=exc, name=name, id=id)

    mock_logger.assert_called_once_with(
        'celery task_unknown name: %s | id: %s | message: %s | error: %s',
        name,
        id,
        message,
        exc,
    )


def test_task_rejected_logging(mocker, notify_api):
    """Test logging for celery task_rejected signal."""
    mock_logger = mocker.patch('app.celery.celery.current_app.logger.exception')

    message = 'Task rejected'
    exc = Exception('TaskRejectedError')

    task_rejected.send(sender=None, message=message, exc=exc)

    mock_logger.assert_called_once_with(
        'celery task_rejected message: %s | error: %s',
        message,
        exc,
    )
