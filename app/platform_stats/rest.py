from datetime import datetime

from flask import Blueprint, jsonify, request

from app.dao.date_util import get_financial_year_for_datetime
from app.dao.fact_billing_dao import (
    fetch_sms_billing_for_all_services, fetch_letter_costs_for_all_services,
    fetch_letter_line_items_for_all_services
)
from collections import defaultdict
from app.platform_stats.strftime_codes import no_pad_month
from app.dao.fact_notification_status_dao import fetch_notification_status_totals_for_all_services, \
    fetch_delivered_notification_stats_by_month
from app.errors import register_errors, InvalidRequest
from app.platform_stats.platform_stats_schema import platform_stats_request
from app.service.statistics import format_admin_stats
from app.schema_validation import validate
from app.utils import get_local_timezone_midnight_in_utc
from app.feature_flags import is_feature_enabled, FeatureFlag


platform_stats_blueprint = Blueprint('platform_stats', __name__)

register_errors(platform_stats_blueprint)


@platform_stats_blueprint.route('')
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

    get_monthly_stats = jsonify(data=fetch_delivered_notification_stats_by_month())
    results = get_monthly_stats["data"]

    monthly_stats = {}
    emails_total = 0
    sms_total = 0
    for line in results:
        date, notification_type, count = line
        year = date[:4]
        year_month = date[:7]
        month = f"{__get_month_name(date)} {year}"
        if month not in monthly_stats:
            monthly_stats[month] = defaultdict(int)
        monthly_stats[month][notification_type] = count
        monthly_stats[month]["total"] += count
        monthly_stats[month]["year_month"] = year_month

        if notification_type == "sms":
            sms_total += count
        elif notification_type == "email":
            emails_total += count

    return {
        "monthly_stats": monthly_stats,
        "emails_total": emails_total,
        "sms_total": sms_total,
        "notifications_total": sms_total + emails_total,
    }


def validate_date_range_is_within_a_financial_year(start_date, end_date):
    try:
        start_date = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_date = datetime.strptime(end_date, "%Y-%m-%d").date()
    except ValueError:
        raise InvalidRequest(message="Input must be a date in the format: YYYY-MM-DD", status_code=400)
    if end_date < start_date:
        raise InvalidRequest(message="Start date must be before end date", status_code=400)

    start_fy = get_financial_year_for_datetime(get_local_timezone_midnight_in_utc(start_date))
    end_fy = get_financial_year_for_datetime(get_local_timezone_midnight_in_utc(end_date))

    if start_fy != end_fy:
        raise InvalidRequest(message="Date must be in a single financial year.", status_code=400)

    return start_date, end_date


@platform_stats_blueprint.route('usage-for-all-services')
def get_usage_for_all_services():
    # TODO: Add defeaults or request validation
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    start_date, end_date = validate_date_range_is_within_a_financial_year(start_date, end_date)

    sms_costs = fetch_sms_billing_for_all_services(start_date, end_date)
    letter_costs = fetch_letter_costs_for_all_services(start_date, end_date)
    letter_breakdown = fetch_letter_line_items_for_all_services(start_date, end_date)

    lb_by_service = [
        (lb.service_id, "{} {} class letters at {}p".format(lb.letters_sent, lb.postage, int(lb.letter_rate * 100)))
        for lb in letter_breakdown
    ]
    combined = {}
    # TODO: Add email costs?
    for s in sms_costs:
        entry = {
            "organisation_id": str(s.organisation_id) if s.organisation_id else "",
            "organisation_name": s.organisation_name or "",
            "service_id": str(s.service_id),
            "service_name": s.service_name,
            "sms_cost": float(s.sms_cost),
            "sms_fragments": s.chargeable_billable_sms,
            "letter_cost": 0,
            "letter_breakdown": ""
        }
        combined[s.service_id] = entry

    for l in letter_costs:
        if l.service_id in combined:
            combined[l.service_id].update({'letter_cost': float(l.letter_cost)})
        else:
            letter_entry = {
                "organisation_id": str(l.organisation_id) if l.organisation_id else "",
                "organisation_name": l.organisation_name or "",
                "service_id": str(l.service_id),
                "service_name": l.service_name,
                "sms_cost": 0,
                "sms_fragments": 0,
                "letter_cost": float(l.letter_cost),
                "letter_breakdown": ""
            }
            combined[l.service_id] = letter_entry
    for service_id, breakdown in lb_by_service:
        combined[service_id]['letter_breakdown'] += (breakdown + '\n')

    # sorting first by name == '' means that blank orgs will be sorted last.
    return jsonify(sorted(combined.values(), key=lambda x: (
        x['organisation_name'] == '',
        x['organisation_name'],
        x['service_name']
    )))


def __get_month_name(date_string):
    month = date_string[5:7].strftime(no_pad_month())

    translated_month = {
        1: "January",
        2: "February",
        3: "March",
        4: "April",
        5: "May",
        6: "June",
        7: "July",
        8: "August",
        9: "September",
        10: "October",
        11: "November",
        12: "December",
    }

    return translated_month.get(month, "Invalid month")
