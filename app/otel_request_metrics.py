import logging
import os
import resource
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

    def observe_rss_bytes(_options) -> list:
        try:
            with open("/proc/self/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        rss_bytes = int(line.split()[1]) * 1024  # kB -> bytes
                        break
                else:
                    raise ValueError("VmRSS not found")
        except OSError:
            # macOS fallback: ru_maxrss reports bytes on macOS
            rss_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return [Observation(rss_bytes, {"worker_pid": str(pid)})]

    meter.create_observable_gauge(
        "notify_api_worker_rss_bytes",
        callbacks=[observe_rss_bytes],
        description="Current RSS memory usage of this Gunicorn worker process",
        unit="By",
    )

    # --- Worker capacity --------------------------------------------------------
    # Total configured concurrency for this pod so dashboards can derive
    # saturation: notify_api_inflight_requests / notify_api_worker_capacity.
    # Emitted without worker_pid because this is a pod-level constant; tagging
    # it per-pid would cause overcounting if dashboards sum across workers.
    _worker_count = int(os.getenv("GUNICORN_WORKERS", "4"))
    _worker_connections = int(os.getenv("GUNICORN_WORKER_CONNECTIONS", "256"))
    _total_capacity = _worker_count * _worker_connections

    def observe_worker_capacity(_options) -> list:
        return [Observation(_total_capacity, {})]

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
    #
    # All four gauge callbacks share a single per-scrape snapshot so engines
    # are resolved only once per collection cycle rather than once per metric.
    # A TTL of 1 s is short enough to be effectively per-scrape while preventing
    # redundant work if the SDK somehow calls callbacks in rapid succession.
    _POOL_STATS_TTL = 1.0  # seconds
    _pool_stats_cache: dict = {"ts": -1.0, "data": {}}  # bind -> {stat: value}
    _pool_stats_lock = threading.Lock()

    def _refresh_pool_stats() -> dict:
        """Collect all pool stats for every bind in one pass. Returns a mapping
        of bind_name -> {stat_fn_name: value} for stats supported by the pool."""
        from app import db as _db

        snapshot: dict = {}
        binds_config = app.config.get("SQLALCHEMY_BINDS") or {}
        bind_names = list(binds_config.keys()) if binds_config else ["default"]
        stat_names = ("checkedout", "checkedin", "overflow", "size")

        for bind in bind_names:
            try:
                engine = _db.get_engine(app, bind=bind if bind != "default" else None)
                bind_stats = {}
                for stat in stat_names:
                    fn = getattr(engine.pool, stat, None)
                    if callable(fn):
                        bind_stats[stat] = fn()
                snapshot[bind] = bind_stats
            except Exception:
                logger.exception("Failed to collect DB pool stats for bind '%s'", bind)

        return snapshot

    def _get_pool_stats() -> dict:
        now = perf_counter()
        with _pool_stats_lock:
            if now - _pool_stats_cache["ts"] >= _POOL_STATS_TTL:
                _pool_stats_cache["data"] = _refresh_pool_stats()
                _pool_stats_cache["ts"] = now
            return _pool_stats_cache["data"]

    def _pool_observations(stat_fn_name: str) -> list:
        return [
            Observation(value, {"db_bind": bind, "worker_pid": str(pid)})
            for bind, stats in _get_pool_stats().items()
            if (value := stats.get(stat_fn_name)) is not None
        ]

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
