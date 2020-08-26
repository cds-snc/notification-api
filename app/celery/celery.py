import time

from celery import Celery, Task
from celery.signals import worker_process_shutdown
from flask import current_app


@worker_process_shutdown.connect
def worker_process_shutdown(sender, signal, pid, exitcode, **kwargs):
    current_app.logger.info('worker shutdown: PID: {} Exitcode: {}'.format(pid, exitcode))


def make_task(app):
    class NotifyTask(Task):
        abstract = True
        start = None

        def on_success(self, retval, task_id, args, kwargs):
            elapsed_time = time.time() - self.start
            app.logger.info(
                "{task_name} took {time}".format(
                    task_name=self.name, time="{0:.4f}".format(elapsed_time)
                )
            )

        def on_failure(self, exc, task_id, args, kwargs, einfo):
            # ensure task will log exceptions to correct handlers
            app.logger.exception('Celery task: {} failed'.format(self.name))
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
            broker=app.config['BROKER_URL'],
            task_cls=make_task(app),
        )

        self.conf.update(
            broker_transport_options=app.config['BROKER_TRANSPORT_OPTIONS'],
            worker_enable_remote_control=app.config['WORKER_ENABLE_REMOTE_CONTROL'],
            enable_utc=app.config['ENABLE_UTC'],
            timezone=app.config['TIMEZONE'],
            accept_content=app.config['ACCEPT_CONTENT'],
            task_serializer=app.config['TASK_SERIALIZER'],
            imports=app.config['IMPORTS'],
            beat_schedule=app.config['BEAT_SCHEDULE'],
            task_queues=app.config['TASK_QUEUES']
        )
