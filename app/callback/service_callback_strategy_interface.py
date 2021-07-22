from celery import Task
from flask import Response


class ServiceCallbackStrategyInterface:
    @staticmethod
    def send_callback(task: Task, payload: dict, url: str, logging_tags: dict, token: str) -> Response:
        raise NotImplementedError
