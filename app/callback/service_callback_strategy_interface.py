class ServiceCallbackStrategyInterface:
    @staticmethod
    def send_callback(self, payload: dict, url: str, logging_tags: dict, token: str) -> None:
        raise NotImplementedError
