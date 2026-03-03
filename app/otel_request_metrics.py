import os
import threading
from time import perf_counter
from typing import Optional

from flask import Flask, g, request


def init_otel_request_metrics(app: Flask) -> None:
    if not app.config.get("OTEL_REQUEST_METRICS_ENABLED", False):
        return

    try:
        from opentelemetry.metrics import Observation, get_meter
    except Exception as e:  # pragma: no cover - depends on runtime injection
        app.logger.warning(f"OTEL request metrics unavailable: {e}")
        return

    pid = os.getpid()
    inflight = 0
    inflight_lock = threading.Lock()

    meter = get_meter("notification-api.request-metrics")
    inflight_counter = meter.create_up_down_counter(
        "notify_api_inflight_requests",
        description="Current number of in-flight API requests in this worker process",
        unit="{request}",
    )
    requests_total = meter.create_counter(
        "notify_api_requests_total",
        description="Total number of API requests handled",
        unit="{request}",
    )
    request_duration_ms = meter.create_histogram(
        "notify_api_request_duration_ms",
        description="Duration of API requests handled by the app process",
        unit="ms",
    )

    def observe_worker_inflight(_options) -> list:
        with inflight_lock:
            current = inflight
        return [Observation(current, {"worker_pid": str(pid)})]

    meter.create_observable_gauge(
        "notify_api_worker_inflight_requests",
        callbacks=[observe_worker_inflight],
        description="In-flight API requests by worker process",
        unit="{request}",
    )

    def decrement_inflight() -> None:
        nonlocal inflight

        if not getattr(g, "_otel_inflight_incremented", False):
            return

        with inflight_lock:
            inflight = max(inflight - 1, 0)

        inflight_counter.add(-1, {"worker_pid": str(pid)})
        g._otel_inflight_incremented = False

    @app.before_request
    def _otel_before_request() -> None:
        nonlocal inflight

        g._otel_request_start = perf_counter()
        g._otel_inflight_incremented = True

        with inflight_lock:
            inflight += 1

        inflight_counter.add(1, {"worker_pid": str(pid)})

    @app.after_request
    def _otel_after_request(response):
        method = request.method
        endpoint = request.endpoint or "unknown"
        status_code = str(response.status_code)

        attrs = {
            "http_method": method,
            "endpoint": endpoint,
            "status_code": status_code,
            "worker_pid": str(pid),
        }

        started = getattr(g, "_otel_request_start", None)
        if started is not None:
            request_duration_ms.record((perf_counter() - started) * 1000, attrs)

        requests_total.add(1, attrs)
        decrement_inflight()
        return response

    @app.teardown_request
    def _otel_teardown_request(_exc: Optional[BaseException]) -> None:
        decrement_inflight()
