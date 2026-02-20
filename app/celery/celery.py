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
            app.logger.info("{task_name} took {time}".format(task_name=self.name, time="{0:.4f}".format(elapsed_time)))

        def on_failure(self, exc, task_id, args, kwargs, einfo):
            # Classify the error and get the root exception
            category, root_exc = classify_error(exc)
            root_exception_type = type(root_exc).__name__ if root_exc else "None"

            # All task failures are errors; classification is in the message prefix
            app.logger.error(
                "%s task_name=%s task_id=%s root_exception=%s exception=%s",
                category.value,
                self.name,
                task_id,
                root_exception_type,
                str(exc),
            )

            # Call parent to ensure default Celery behavior still runs
            super().on_failure(exc, task_id, args, kwargs, einfo)

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
