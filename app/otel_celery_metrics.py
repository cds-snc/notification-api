import os
import threading
from time import perf_counter
from typing import Dict, Optional, Tuple

from flask import Flask


def init_otel_celery_metrics(app: Flask) -> None:
    if not app.config.get("OTEL_REQUEST_METRICS_ENABLED", False):
        return

    try:
        from opentelemetry.metrics import Observation, get_meter
    except Exception as e:  # pragma: no cover - depends on runtime injection
        app.logger.warning(f"OTEL celery metrics unavailable: {e}")
        return

    try:
        from celery import signals
    except ImportError as e:  # pragma: no cover
        app.logger.warning(f"Celery not available for OTEL metrics: {e}")
        return

    from app.celery.error_registry import classify_error

    pid = os.getpid()
    inflight = 0
    inflight_lock = threading.Lock()

    # Maps task_id -> (start_time, task_name) so we can record duration on postrun.
    task_start_times: Dict[str, Tuple[float, str]] = {}
    task_start_lock = threading.Lock()

    meter = get_meter("notification-api.celery-metrics")

    inflight_counter = meter.create_up_down_counter(
        "notify_celery_inflight_tasks",
        description="Current number of in-flight Celery tasks in this worker process",
        unit="{task}",
    )
    tasks_total = meter.create_counter(
        "notify_celery_tasks_total",
        description="Total number of Celery tasks processed",
        unit="{task}",
    )
    task_duration_ms = meter.create_histogram(
        "notify_celery_task_duration_ms",
        description="Duration of Celery task execution",
        unit="ms",
    )
    task_retries_total = meter.create_counter(
        "notify_celery_task_retries_total",
        description="Number of Celery task retry attempts, broken down by error category",
        unit="{retry}",
    )
    task_failures_total = meter.create_counter(
        "notify_celery_task_failures_total",
        description="Number of permanently failed Celery tasks (retries exhausted), broken down by error category",
        unit="{task}",
    )

    def observe_worker_inflight(_options) -> list:
        with inflight_lock:
            current = inflight
        return [Observation(current, {"worker_pid": str(pid)})]

    meter.create_observable_gauge(
        "notify_celery_worker_inflight_tasks",
        callbacks=[observe_worker_inflight],
        description="In-flight Celery tasks by worker process",
        unit="{task}",
    )

    # NOTE: weak=False is required on all signal connections.
    # Celery signals hold weak references to handlers by default, so handlers
    # defined inside this function would be garbage-collected once init returns,
    # silently dropping every metric except the ObservableGauge (whose callback
    # the OTEL SDK holds with a strong reference).

    def _otel_task_prerun(task_id: Optional[str] = None, task=None, **kwargs) -> None:
        nonlocal inflight

        if task_id is None:
            return

        task_name = task.name if task else "unknown"
        now = perf_counter()

        with task_start_lock:
            task_start_times[task_id] = (now, task_name)

        with inflight_lock:
            inflight += 1

        inflight_counter.add(1, {"task_name": task_name, "worker_pid": str(pid)})

    def _otel_task_postrun(task_id: Optional[str] = None, task=None, state: Optional[str] = None, **kwargs) -> None:
        nonlocal inflight

        with task_start_lock:
            entry = task_start_times.pop(task_id, None) if task_id is not None else None

        if entry is not None:
            started, task_name = entry
        else:
            task_name = task.name if task else "unknown"
            started = None

        # state values from Celery: SUCCESS, FAILURE, RETRY, REVOKED
        status = (state or "unknown").lower()

        attrs = {
            "task_name": task_name,
            "status": status,
            "worker_pid": str(pid),
        }

        if started is not None:
            task_duration_ms.record((perf_counter() - started) * 1000, attrs)

        tasks_total.add(1, attrs)

        with inflight_lock:
            inflight = max(inflight - 1, 0)

        inflight_counter.add(-1, {"task_name": task_name, "worker_pid": str(pid)})

    def _otel_task_retry(sender=None, reason=None, request=None, **kwargs) -> None:
        task_name = sender.name if sender else "unknown"
        retry_count = request.retries if request else 0
        exception = reason if isinstance(reason, Exception) else None
        error_category, _ = classify_error(exception)

        task_retries_total.add(
            1,
            {
                "task_name": task_name,
                "error_category": error_category.value,
                "retry_number": str(retry_count),
                "worker_pid": str(pid),
            },
        )

    def _otel_task_failure(sender=None, task_id=None, exception=None, **kwargs) -> None:
        task_name = sender.name if sender else "unknown"
        error_category, _ = classify_error(exception)

        task_failures_total.add(
            1,
            {
                "task_name": task_name,
                "error_category": error_category.value,
                "worker_pid": str(pid),
            },
        )

    signals.task_prerun.connect(_otel_task_prerun, weak=False)
    signals.task_postrun.connect(_otel_task_postrun, weak=False)
    signals.task_retry.connect(_otel_task_retry, weak=False)
    signals.task_failure.connect(_otel_task_failure, weak=False)
