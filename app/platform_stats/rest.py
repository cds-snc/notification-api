from datetime import datetime

from flask import Blueprint, jsonify, request

from app.authentication.auth import requires_admin_auth
from app.dao.fact_notification_status_dao import (
    fetch_notification_status_totals_for_all_services,
    fetch_delivered_notification_stats_by_month,
)
from app.errors import register_errors
from app.platform_stats.platform_stats_schema import platform_stats_request
from app.service.statistics import format_admin_stats
from app.schema_validation import validate
from app.feature_flags import is_feature_enabled, FeatureFlag


platform_stats_blueprint = Blueprint('platform_stats', __name__)

register_errors(platform_stats_blueprint)


@platform_stats_blueprint.route('')
@requires_admin_auth()
def get_platform_stats():
    if request.args:
        validate(request.args, platform_stats_request)

    # If start and end date are not set, we are expecting today's stats.
    today = str(datetime.utcnow().date())

    start_date = datetime.strptime(request.args.get('start_date', today), '%Y-%m-%d').date()
    end_date = datetime.strptime(request.args.get('end_date', today), '%Y-%m-%d').date()
    data = fetch_notification_status_totals_for_all_services(start_date=start_date, end_date=end_date)
    stats = format_admin_stats(data)

    return jsonify(stats)


@platform_stats_blueprint.route('/monthly', methods=['GET'])
def get_monthly_platform_stats():
    if not is_feature_enabled(FeatureFlag.PLATFORM_STATS_ENABLED):
        raise NotImplementedError

    results = fetch_delivered_notification_stats_by_month()

    platform_stats_keys = ['date', 'notification_type', 'count']
    notify_monthly_stats = {'data': []}

    for stats_list in results:
        for item in range(len(stats_list)):
            formatted_dict = dict(zip(platform_stats_keys, stats_list))
        notify_monthly_stats['data'].append(formatted_dict)

    return jsonify(notify_monthly_stats)
