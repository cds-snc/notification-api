from flask import Blueprint, jsonify, request
from app.dao.notifications_dao import dao_get_last_template_usage
from app.dao.templates_dao import dao_get_template_by_id_and_service_id
from app.dao.fact_notification_status_dao import fetch_notification_status_for_service_for_today_and_7_previous_days

from app.schemas import notification_with_template_schema
from app.errors import register_errors, InvalidRequest

template_statistics = Blueprint('template_statistics',
                                __name__,
                                url_prefix='/service/<service_id>/template-statistics')

register_errors(template_statistics)


@template_statistics.route('')
def get_template_statistics_for_service_by_day(service_id):
    whole_days = request.args.get('whole_days', request.args.get('limit_days', ''))
    try:
        whole_days = int(whole_days)
    except ValueError:
        error = '{} is not an integer'.format(whole_days)
        message = {'whole_days': [error]}
        raise InvalidRequest(message, status_code=400)

    if whole_days < 0 or whole_days > 7:
        raise InvalidRequest({'whole_days': ['whole_days must be between 0 and 7']}, status_code=400)
    data = fetch_notification_status_for_service_for_today_and_7_previous_days(
        service_id, by_template=True, limit_days=whole_days
    )

    return jsonify(data=[
        {
            'count': row.count,
            'template_id': str(row.template_id),
            'template_name': row.template_name,
            'template_type': row.notification_type,
            'is_precompiled_letter': row.is_precompiled_letter,
            'status': row.status
        }
        for row in data
    ])

# TODO: Rename method (and endpoint?)
@template_statistics.route('/<template_id>')
def get_template_statistics_for_template_id(service_id, template_id):
    template = dao_get_template_by_id_and_service_id(template_id, service_id)

    data = None
    notification = dao_get_last_template_usage(template_id, template.template_type, template.service_id)
    if notification:
        data = notification_with_template_schema.dump(notification).data

    return jsonify(data=data)
