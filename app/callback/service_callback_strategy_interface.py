from app.models import ServiceCallback


class ServiceCallbackStrategyInterface:
    @staticmethod
    def send_callback(
        callback: ServiceCallback,
        payload: dict,
        logging_tags: dict,
    ) -> None:
        raise NotImplementedError
