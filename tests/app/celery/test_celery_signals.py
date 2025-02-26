from unittest.mock import MagicMock
from celery.signals import (
    task_prerun,
    task_postrun,
    task_internal_error,
    task_revoked,
    task_unknown,
    task_rejected,
)
from billiard.einfo import ExceptionInfo


def test_task_prerun_logging(mocker, notify_api):
    """Test logging for celery task_prerun signal."""
    mock_logger = mocker.patch('app.celery.celery.current_app.logger.debug')

    task = MagicMock(name='dummy_task')
    task_id = '12345'

    task_prerun.send(sender=None, task_id=task_id, task=task)

    mock_logger.assert_called_once_with(f'celery task_prerun task_id: {task_id} | task_name: {task.name}')


def test_task_postrun_logging(mocker, notify_api):
    """Test logging for celery task_postrun signal."""
    mock_logger = mocker.patch('app.celery.celery.current_app.logger.debug')

    task = MagicMock(name='dummy_task')
    task_id = '12345'

    task_postrun.send(sender=None, task_id=task_id, task=task)

    mock_logger.assert_called_once_with(f'celery task_postrun task_id: {task_id} | task_name: {task.name}')


def test_task_internal_error_logging(mocker, notify_api):
    """Test logging for celery task_internal_error signal."""
    mock_logger = mocker.patch('app.celery.celery.current_app.logger.exception')

    task_id = '12345'

    try:
        raise ValueError('Test error message')
    except ValueError:
        einfo = ExceptionInfo()

    task_internal_error.send(sender=None, task_id=task_id, einfo=einfo)

    mock_logger.assert_called_once_with(f'celery task_internal_error task_id: {task_id} | einfo: {einfo}')


def test_task_revoked_logging(mocker, notify_api):
    """Test logging for celery task_revoked signal."""
    mock_logger = mocker.patch('app.celery.celery.current_app.logger.error')

    request = MagicMock(task='dummy_task', id='12345')
    terminated = True
    signum = 9

    task_revoked.send(sender=None, request=request, terminated=terminated, signum=signum)

    mock_logger.assert_called_once_with(
        f'celery task_revoked request_task: {request.task} | request_id: {request.id} | terminated: {terminated} | signum: {signum}'
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
        f'celery task_unknown name: {name} | id: {id} | message: {message} | error: {exc}'
    )


def test_task_rejected_logging(mocker, notify_api):
    """Test logging for celery task_rejected signal."""
    mock_logger = mocker.patch('app.celery.celery.current_app.logger.exception')

    message = 'Task rejected'
    exc = Exception('TaskRejectedError')

    task_rejected.send(sender=None, message=message, exc=exc)

    mock_logger.assert_called_once_with(f'celery task_rejected message: {message} | error: {exc}')
