import time

from flask import current_app

from celery import Celery, Task
from celery.signals import worker_process_shutdown


@worker_process_shutdown.connect  # type: ignore
def worker_process_shutdown(sender, signal, pid, exitcode, **kwargs):
    current_app.logger.info("worker shutdown: PID: {} Exitcode: {}".format(pid, exitcode))


def make_task(app):
    from app import statsd_client

    class NotifyTask(Task):
        abstract = True
        start = None

        def on_success(self, retval, task_id, args, kwargs):
            task_name: str = self.name
            now: float = time.time()
            statsd_client.timing_with_dates(f"celery-task.{task_name}.total-time", now, self.start)

            elapsed_time = now - self.start
            app.logger.debug("{task_name} took {time}".format(task_name=task_name, time="{0:.4f}".format(elapsed_time)))

        def on_failure(self, exc, task_id, args, kwargs, einfo):
            # ensure task will log exceptions to correct handlers
            app.logger.exception("Celery task: {} failed".format(self.name))
            super().on_failure(exc, task_id, args, kwargs, einfo)

        def __call__(self, *args, **kwargs):
            # ensure task has flask context to access config, logger, etc
            with app.app_context():
                self.start: float = time.time()
                return super().__call__(*args, **kwargs)

    return NotifyTask


class NotifyCelery(Celery):
    def init_app(self, app):
        super().__init__(
            app.import_name,
            broker=app.config["BROKER_URL"],
            task_cls=make_task(app),
        )

        # See https://docs.celeryproject.org/en/stable/userguide/configuration.html
        self.conf.update(
            {
                "beat_schedule": app.config["CELERYBEAT_SCHEDULE"],
                "imports": app.config["CELERY_IMPORTS"],
                "task_serializer": app.config["CELERY_TASK_SERIALIZER"],
                "timezone": app.config["CELERY_TIMEZONE"],
                "broker_transport_options": app.config["BROKER_TRANSPORT_OPTIONS"],
                "task_queues": app.config["CELERY_QUEUES"],
                "accept_content": app.config["CELERY_ACCEPT_CONTENT"],
            }
        )
