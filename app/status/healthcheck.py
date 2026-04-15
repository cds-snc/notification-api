import random
import time
from datetime import datetime, timezone

from flask import Blueprint, current_app, jsonify, request

from app import db, version
from app.dao.organisation_dao import dao_count_organsations_with_live_services
from app.dao.services_dao import dao_count_live_services

status = Blueprint("status", __name__)


@status.route("/", methods=["GET"])
@status.route("/_status", methods=["GET", "POST"])
def show_status():
    if request.args.get("simple", None):
        return jsonify(status="ok"), 200
    else:
        return (
            jsonify(
                current_time_utc=str(str(datetime.now(timezone.utc))),
                status="ok",  # This should be considered part of the public API
                commit_sha=version.__commit_sha__,
                build_time=version.__time__,
                db_version=get_db_version(),
            ),
            200,
        )


@status.route("/_status/live-service-and-organisation-counts")
def live_service_and_organisation_counts():
    return (
        jsonify(
            organisations=dao_count_organsations_with_live_services(),
            services=dao_count_live_services(),
        ),
        200,
    )


def get_db_version():
    query = "SELECT version_num FROM alembic_version"
    full_name = db.session.execute(query).fetchone()[0]
    return full_name


@status.route("/_status/benchmark", methods=["GET"])
def benchmark():
    """Simulates a DB call with a configurable sleep for throughput testing.

    Requires the FF_BENCHMARK_ENDPOINT feature flag to be enabled.

    Query params:
        delay_ms (int): target sleep duration in milliseconds (default: 100).
                        Actual sleep is randomised within ±20% of this value.
    """
    if not current_app.config.get("FF_BENCHMARK_ENDPOINT"):
        return jsonify(status="not found"), 404

    target_ms = int(request.args.get("delay_ms", 100))
    jitter_ms = target_ms * 0.2
    actual_ms = random.uniform(target_ms - jitter_ms, target_ms + jitter_ms)
    time.sleep(actual_ms / 1000)

    return jsonify(status="ok", simulated_delay_ms=round(actual_ms, 2)), 200
