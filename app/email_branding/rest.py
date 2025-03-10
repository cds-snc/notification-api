from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError

from app.dao.email_branding_dao import (
    dao_create_email_branding,
    dao_get_email_branding_by_id,
    dao_get_email_branding_options,
    dao_update_email_branding,
)
from app.email_branding.email_branding_schema import (
    post_create_email_branding_schema,
    post_update_email_branding_schema,
)
from app.errors import CannotSaveDuplicateEmailBrandingError, register_errors
from app.models import EmailBranding
from app.schema_validation import validate

email_branding_blueprint = Blueprint("email_branding", __name__)
register_errors(email_branding_blueprint)


@email_branding_blueprint.route("", methods=["GET"])
def get_email_branding_options():
    filter_by_organisation_id = request.args.get("organisation_id", None)
    email_branding_options = [
        o.serialize() for o in dao_get_email_branding_options(filter_by_organisation_id=filter_by_organisation_id)
    ]
    return jsonify(email_branding=email_branding_options)


@email_branding_blueprint.route("/<uuid:email_branding_id>", methods=["GET"])
def get_email_branding_by_id(email_branding_id):
    email_branding = dao_get_email_branding_by_id(email_branding_id)
    return jsonify(email_branding=email_branding.serialize())


@email_branding_blueprint.route("", methods=["POST"])
def create_email_branding():
    data = request.get_json()

    validate(data, post_create_email_branding_schema)
    email_branding = EmailBranding(**data)

    if "text" not in data.keys():
        email_branding.text = email_branding.name

    try:
        dao_create_email_branding(email_branding)
    except IntegrityError as e:
        if "uq_email_branding_name" in str(e):
            raise CannotSaveDuplicateEmailBrandingError()

    return jsonify(data=email_branding.serialize()), 201


@email_branding_blueprint.route("/<uuid:email_branding_id>", methods=["POST"])
def update_email_branding(email_branding_id):
    data = request.get_json()
    validate(data, post_update_email_branding_schema)

    if "text" not in data.keys() and "name" in data.keys():
        data["text"] = data["name"]

    fetched_email_branding = dao_get_email_branding_by_id(email_branding_id)
    try:
        dao_update_email_branding(fetched_email_branding, **data)
    except IntegrityError as e:
        if "uq_email_branding_name" in str(e):
            raise CannotSaveDuplicateEmailBrandingError()

    return jsonify(data=fetched_email_branding.serialize()), 200
