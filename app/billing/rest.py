from flask import Blueprint, jsonify, request

from app.billing.billing_schemas import (
    serialize_ft_billing_remove_emails,
    serialize_ft_billing_yearly_totals,
)
from app.dao.fact_billing_dao import (
    fetch_monthly_billing_for_year,
    fetch_billing_totals_for_year,
)

from app.errors import register_errors

billing_blueprint = Blueprint('billing', __name__, url_prefix='/service/<uuid:service_id>/billing')


register_errors(billing_blueprint)


@billing_blueprint.route('/ft-monthly-usage')
@billing_blueprint.route('/monthly-usage')
def get_yearly_usage_by_monthly_from_ft_billing(service_id):
    try:
        year = int(request.args.get('year'))
    except TypeError:
        return jsonify(result='error', message='No valid year provided'), 400
    results = fetch_monthly_billing_for_year(service_id=service_id, year=year)
    data = serialize_ft_billing_remove_emails(results)
    return jsonify(data)


@billing_blueprint.route('/ft-yearly-usage-summary')
@billing_blueprint.route('/yearly-usage-summary')
def get_yearly_billing_usage_summary_from_ft_billing(service_id):
    try:
        year = int(request.args.get('year'))
    except TypeError:
        return jsonify(result='error', message='No valid year provided'), 400

    billing_data = fetch_billing_totals_for_year(service_id, year)
    data = serialize_ft_billing_yearly_totals(billing_data)
    return jsonify(data)
