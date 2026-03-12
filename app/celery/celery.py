import time

from environs import Env
from flask import current_app

from app.celery.error_registry import classify_error
from celery import Celery, Task, signals
from celery.signals import worker_process_shutdown


@worker_process_shutdown.connect  # type: ignore
def worker_process_shutdown(sender, signal, pid, exitcode, **kwargs):
    current_app.logger.info("worker shutdown: PID: {} Exitcode: {}".format(pid, exitcode))


def make_task(app):
    class NotifyTask(Task):
        abstract = True
        start = None

        def on_success(self, retval, task_id, args, kwargs):
            elapsed_time = time.time() - self.start
            app.logger.info("{task_name} took {time}s".format(task_name=self.name, time="{0:.4f}".format(elapsed_time)))

        def __call__(self, *args, **kwargs):
            # ensure task has flask context to access config, logger, etc
            with app.app_context():
                self.start = time.time()
                return super().__call__(*args, **kwargs)

    return NotifyTask


class NotifyCelery(Celery):
    def init_app(self, app):
        super().__init__(
            app.import_name,
            broker=app.config["BROKER_URL"],
            task_cls=make_task(app),
        )

        ff_enable_otel = Env().bool("FF_ENABLE_OTEL", default=False)
        if not ff_enable_otel:
            from app.aws.xray_celery_handlers import (
                xray_after_task_publish,
                xray_before_task_publish,
                xray_task_failure,
                xray_task_postrun,
                xray_task_prerun,
            )

            # Register the X-Ray handlers
            signals.after_task_publish.connect(xray_after_task_publish)
            signals.before_task_publish.connect(xray_before_task_publish)
            signals.task_failure.connect(xray_task_failure)
            signals.task_postrun.connect(xray_task_postrun)
            signals.task_prerun.connect(xray_task_prerun)

        # See https://docs.celeryproject.org/en/stable/userguide/configuration.html
        self.conf.update(
            {
                "beat_schedule": app.config["CELERYBEAT_SCHEDULE"],
                "imports": app.config["CELERY_IMPORTS"],
                "task_serializer": app.config["CELERY_TASK_SERIALIZER"],
                "enable_utc": app.config["CELERY_ENABLE_UTC"],
                "timezone": app.config["CELERY_TIMEZONE"],
                "broker_transport_options": app.config["BROKER_TRANSPORT_OPTIONS"],
                "task_queues": app.config["CELERY_QUEUES"],
                "accept_content": app.config["CELERY_ACCEPT_CONTENT"],
            }
        )


# Register Celery signal handlers that classify errors using the maps defined in
# app.celery.error_registry (both by exception class name and message substrings).


@signals.task_retry.connect
def classify_celery_task_retry(sender=None, reason=None, request=None, einfo=None, **kwargs):
    """Fires on each retry — classifies the transient error."""
    task_name = sender.name if sender else "unknown"
    task_id = request.id if request else "unknown"
    exception = reason if isinstance(reason, Exception) else None
    category, root_exc = classify_error(exception)
    root_exception_type = type(root_exc).__name__ if root_exc else "None"

    current_app.logger.warning(
        "%s task_name=%s task_id=%s root_exception=%s exception=%s",
        category.value,
        task_name,
        task_id,
        root_exception_type,
        str(exception),
    )


@signals.task_failure.connect
def classify_celery_task_failure(sender=None, task_id=None, exception=None, **kwargs):
    """Fires when retries are exhausted — classifies the permanent failure."""
    task_name = sender.name if sender else "unknown"
    category, root_exc = classify_error(exception)
    root_exception_type = type(root_exc).__name__ if root_exc else "None"

    current_app.logger.warning(
        "%s task_name=%s task_id=%s root_exception=%s exception=%s",
        category.value,
        task_name,
        task_id,
        root_exception_type,
        str(exception),
    )


@signals.task_internal_error.connect
def classify_celery_task_internal_error(sender=None, task_id=None, exception=None, **kwargs):
    """Fires on errors outside the task body (e.g. serialization, worker crashes)."""
    task_name = sender.name if sender else "unknown"
    category, root_exc = classify_error(exception)
    root_exception_type = type(root_exc).__name__ if root_exc else "None"

    current_app.logger.warning(
        "%s task_name=%s task_id=%s root_exception=%s exception=%s",
        category.value,
        task_name,
        task_id,
        root_exception_type,
        str(exception),
    )


@signals.task_unknown.connect
def classify_celery_task_unknown(sender=None, name=None, message=None, **kwargs):
    """Fires when a worker receives a task it doesn't recognise."""
    exception = Exception(f"Unknown task: {name} message={message}")
    category, root_exc = classify_error(exception)
    root_exception_type = type(root_exc).__name__ if root_exc else "None"
    # Extract only safe metadata from the broker message — never log the body/args
    task_id = "unknown"
    if message is not None:
        try:
            task_id = (getattr(message, "headers", None) or {}).get("id") or "unknown"
        except Exception:
            pass

    current_app.logger.warning(
        "%s task_name=%s task_id=%s root_exception=%s",
        category.value,
        name or "unknown",
        task_id,
        root_exception_type,
    )
