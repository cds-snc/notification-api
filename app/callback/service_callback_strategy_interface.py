from celery import Task


class ServiceCallbackStrategyInterface:
    @staticmethod
    def send_callback(task: Task, payload: dict, url: str, logging_tags: dict, token: str) -> None:
        raise NotImplementedError
