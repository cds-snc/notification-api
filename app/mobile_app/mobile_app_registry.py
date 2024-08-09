from typing import List
from flask import current_app
from .mobile_app_types import MobileAppType
from .mobile_app import MobileApp


class MobileAppRegistry:
    _instance = None

    def __new__(
        cls,
        *args,
        **kwargs,
    ):
        if not cls._instance:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self._registry = {}
        for type in MobileAppType:
            try:
                app = MobileApp(type)
            except ValueError as e:
                current_app.logger.exception(e)
            else:
                self._registry[type] = app

    def get_app(
        self,
        app_type: MobileAppType,
    ) -> MobileApp:
        return self._registry.get(app_type)

    def get_registered_apps(self) -> List[MobileAppType]:
        return list(self._registry.keys())
