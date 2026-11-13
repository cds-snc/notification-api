from flask import Flask

import app as app_package
from app.otel_request_metrics import init_otel_request_metrics


class FakePool:
    def checkedout(self):
        return 1

    def checkedin(self):
        return 2

    def overflow(self):
        return 3

    def size(self):
        return 4


class FakeEngine:
    pool = FakePool()


class FakeDatabase:
    @property
    def engines(self):
        from flask import current_app

        current_app.name
        return {None: FakeEngine()}


class FakeMeter:
    def __init__(self):
        self.callbacks = {}

    def create_counter(self, *args, **kwargs):
        return object()

    def create_histogram(self, *args, **kwargs):
        return object()

    def create_observable_gauge(self, name, callbacks, **kwargs):
        self.callbacks[name] = callbacks[0]

    def create_up_down_counter(self, *args, **kwargs):
        return object()


def test_db_pool_metrics_resolve_engines_with_an_app_context(monkeypatch):
    app = Flask(__name__)
    meter = FakeMeter()
    monkeypatch.setattr("opentelemetry.metrics.get_meter", lambda _: meter)
    monkeypatch.setattr(app_package, "db", FakeDatabase())

    init_otel_request_metrics(app)

    observations = meter.callbacks["notify_api_db_pool_size"](None)

    assert len(observations) == 1
    assert observations[0].value == 4
