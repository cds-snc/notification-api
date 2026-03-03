import logging
import os
import resource
import sys
import threading
from time import perf_counter
from typing import Optional

from flask import Flask, g, request

logger = logging.getLogger(__name__)


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

    # --- RSS memory --------------------------------------------------------------
    _is_macos = sys.platform == "darwin"

    def observe_rss_bytes(_options) -> list:
        rss_raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # macOS reports bytes; Linux reports kilobytes
        rss_bytes = rss_raw if _is_macos else rss_raw * 1024
        return [Observation(rss_bytes, {"worker_pid": str(pid)})]

    meter.create_observable_gauge(
        "notify_api_worker_rss_bytes",
        callbacks=[observe_rss_bytes],
        description="RSS memory usage of this Gunicorn worker process",
        unit="By",
    )

    # --- Worker capacity --------------------------------------------------------
    # Total configured concurrency for this pod so dashboards can derive
    # saturation: notify_api_inflight_requests / notify_api_worker_capacity.
    _worker_count = int(os.getenv("GUNICORN_WORKERS", "4"))
    _worker_connections = int(os.getenv("GUNICORN_WORKER_CONNECTIONS", "256"))
    _total_capacity = _worker_count * _worker_connections

    def observe_worker_capacity(_options) -> list:
        return [Observation(_total_capacity, {"worker_pid": str(pid)})]

    meter.create_observable_gauge(
        "notify_api_worker_capacity",
        callbacks=[observe_worker_capacity],
        description=(
            "Configured maximum concurrent request capacity for this pod "
            "(GUNICORN_WORKERS x GUNICORN_WORKER_CONNECTIONS). "
            "Divide notify_api_inflight_requests by this to get the saturation ratio."
        ),
        unit="{request}",
    )

    # --- SQLAlchemy connection pool ---------------------------------------------
    # NullPool (used when SQLALCHEMY_DISABLE_POOL=true) has no pool stats;
    # getattr guards against that gracefully.
    def _pool_observations(stat_fn_name: str) -> list:
        # Deferred import to avoid circular dependency at module load time.
        from app import db as _db

        observations = []
        binds_config = app.config.get("SQLALCHEMY_BINDS") or {}
        bind_names = list(binds_config.keys()) if binds_config else ["default"]

        for bind in bind_names:
            try:
                engine = _db.get_engine(app, bind=bind if bind != "default" else None)
                fn = getattr(engine.pool, stat_fn_name, None)
                if callable(fn):
                    observations.append(Observation(fn(), {"db_bind": bind, "worker_pid": str(pid)}))
            except Exception:
                # Metrics collection is best-effort; log and skip failures for this bind.
                logger.exception("Failed to collect DB pool metric '%s' for bind '%s'", stat_fn_name, bind)

        return observations

    meter.create_observable_gauge(
        "notify_api_db_pool_checkedout",
        callbacks=[lambda _: _pool_observations("checkedout")],
        description="DB connections currently checked out from the SQLAlchemy pool",
        unit="{connection}",
    )
    meter.create_observable_gauge(
        "notify_api_db_pool_checkedin",
        callbacks=[lambda _: _pool_observations("checkedin")],
        description="Idle DB connections currently checked in to the SQLAlchemy pool",
        unit="{connection}",
    )
    meter.create_observable_gauge(
        "notify_api_db_pool_overflow",
        callbacks=[lambda _: _pool_observations("overflow")],
        description=(
            "Current overflow connection count. Positive = active overflow connections in use; "
            "negative = unused overflow capacity still available."
        ),
        unit="{connection}",
    )
    meter.create_observable_gauge(
        "notify_api_db_pool_size",
        callbacks=[lambda _: _pool_observations("size")],
        description="Configured fixed size of the SQLAlchemy connection pool (excludes max_overflow)",
        unit="{connection}",
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
