from celery import Task

from app.models import ServiceCallback


class ServiceCallbackStrategyInterface:
    @staticmethod
    def send_callback(task: Task, callback: ServiceCallback, payload: dict, logging_tags: dict) -> None:
        raise NotImplementedError
