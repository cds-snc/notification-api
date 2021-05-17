from flask import request, jsonify, Blueprint, current_app

from app.authentication.auth import validate_admin_auth
from app.dao.service_sms_sender_dao import (
    dao_add_sms_sender_for_service,
    dao_update_service_sms_sender,
    archive_sms_sender,
    dao_get_service_sms_sender_by_id,
    dao_get_sms_senders_by_service_id
)
from app.service.exceptions import SmsSenderDefaultValidationException, SmsSenderInboundNumberIntegrityException
from app.dao.services_dao import dao_fetch_service_by_id
from app.errors import register_errors
from app.schema_validation import validate
from app.service.service_senders_schema import add_service_sms_sender_request, update_service_sms_sender_request


def _validate_service_exists():
    dao_fetch_service_by_id(request.view_args.get('service_id'))


service_sms_sender_blueprint = Blueprint(
    'service_sms_sender',
    __name__,
    url_prefix='/service/<uuid:service_id>/sms-sender'
)
service_sms_sender_blueprint.before_request(validate_admin_auth)
service_sms_sender_blueprint.before_request(_validate_service_exists)


@service_sms_sender_blueprint.errorhandler(SmsSenderDefaultValidationException)
@service_sms_sender_blueprint.errorhandler(SmsSenderInboundNumberIntegrityException)
def handle_errors(error):
    current_app.logger.info(error)
    return jsonify(result='error', message=str(error)), 400


register_errors(service_sms_sender_blueprint)


@service_sms_sender_blueprint.route('', methods=['GET'])
def get_service_sms_senders_for_service(service_id):
    sms_senders = dao_get_sms_senders_by_service_id(service_id=service_id)
    return jsonify([sms_sender.serialize() for sms_sender in sms_senders]), 200


@service_sms_sender_blueprint.route('', methods=['POST'])
def add_service_sms_sender(service_id):
    form = validate(request.get_json(), add_service_sms_sender_request)
    new_sms_sender = dao_add_sms_sender_for_service(service_id=service_id, **form)
    return jsonify(new_sms_sender.serialize()), 201


@service_sms_sender_blueprint.route('/<uuid:sms_sender_id>', methods=['GET'])
def get_service_sms_sender_by_id(service_id, sms_sender_id):
    sms_sender = dao_get_service_sms_sender_by_id(
        service_id=service_id,
        service_sms_sender_id=sms_sender_id
    )
    return jsonify(sms_sender.serialize()), 200


@service_sms_sender_blueprint.route('/<uuid:sms_sender_id>', methods=['POST'])
def update_service_sms_sender(service_id, sms_sender_id):
    form = validate(request.get_json(), update_service_sms_sender_request)
    updated_sms_sender = dao_update_service_sms_sender(
        service_id=service_id,
        service_sms_sender_id=sms_sender_id,
        **form
    )
    return jsonify(updated_sms_sender.serialize()), 200


@service_sms_sender_blueprint.route('/<uuid:sms_sender_id>/archive', methods=['POST'])
def delete_service_sms_sender(service_id, sms_sender_id):
    sms_sender = archive_sms_sender(service_id, sms_sender_id)

    return jsonify(data=sms_sender.serialize()), 200
