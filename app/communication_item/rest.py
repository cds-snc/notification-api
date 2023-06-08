""" Implement CRUD endpoints for the CommunicationItem model. """

import psycopg2
from app import db
from app.communication_item.communication_item_schemas import (
    communication_item_patch_schema,
    communication_item_post_schema,
)
from app.errors import register_errors
from app.models import CommunicationItem
from app.schemas import communication_item_schema
from flask import Blueprint, current_app, jsonify, request
from jsonschema import validate, ValidationError
from sqlalchemy.exc import SQLAlchemyError

communication_item_blueprint = Blueprint("communication_item", __name__, url_prefix="/communication-item")
register_errors(communication_item_blueprint)


#############
# Create
#############

@communication_item_blueprint.route('', methods=["POST"])
def create_communication_item():
    request_data = request.get_json()

    try:
        validate(request_data, communication_item_post_schema)
    except ValidationError as e:
        return {
            "errors": [
                {
                    "error": "ValidationError",
                    "message": e.message,
                }
            ]
        }, 400

    communication_item = CommunicationItem(**request_data)
    db.session.add(communication_item)

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        return {
            "errors": [
                {
                    "error": e.__class__.__name__,
                    "message": str(e.orig).split('\n')[0],
                }
            ]
        }, 400
    except psycopg2.Error as e:
        return {
            "errors": [
                {
                    "error": e.__class__.__name__,
                    "message": e.pgerror,
                }
            ]
        }, 400
    except Exception as e:
        current_app.logger.exception(e)
        raise

    return communication_item_schema.dump(communication_item).data, 201


#############
# Retrieve
#############

@communication_item_blueprint.route('', methods=["GET"])
def get_all_communication_items():
    communication_items = CommunicationItem.query.all()
    return jsonify(data=communication_item_schema.dump(communication_items, many=True).data)


@communication_item_blueprint.route("/<communication_item_id>", methods=["GET"])
def get_communication_item(communication_item_id):
    communication_item = CommunicationItem.query.get(communication_item_id)

    if communication_item is None:
        return {
            "errors": [
                {
                    "error": "NotFound",
                    "message": "That communication item does not exist.",
                }
            ]
        }, 404

    return communication_item_schema.dump(communication_item).data


#############
# Update
#############

@communication_item_blueprint.route("/<communication_item_id>", methods=["PATCH"])
def partially_update_communication_item(communication_item_id):
    request_data = request.get_json()

    try:
        validate(request_data, communication_item_patch_schema)
    except ValidationError as e:
        return {
            "errors": [
                {
                    "error": "ValidationError",
                    "message": e.message,
                }
            ]
        }, 400

    communication_item = CommunicationItem.query.get(communication_item_id)

    if communication_item is None:
        return {
            "errors": [
                {
                    "error": "NotFound",
                    "message": "That communication item does not exist.",
                }
            ]
        }, 404

    db.session.add(communication_item)

    for key, value in request.get_json().items():
        setattr(communication_item, key, value)

    try:
        db.session.commit()
    except SQLAlchemyError as e:
        return {
            "errors": [
                {
                    "error": e.__class__.__name__,
                    "message": str(e.orig).split('\n')[0],
                }
            ]
        }, 400
    except psycopg2.Error as e:
        return {
            "errors": [
                {
                    "error": e.__class__.__name__,
                    "message": e.pgerror,
                }
            ]
        }, 400
    except Exception as e:
        current_app.logger.exception(e)
        raise

    return communication_item_schema.dump(communication_item).data, 200


#############
# Delete
#############

@communication_item_blueprint.route("/<communication_item_id>", methods=["DELETE"])
def delete_communication_item(communication_item_id):
    rows_deleted = CommunicationItem.query.filter_by(id=communication_item_id).delete()
    db.session.commit()

    if rows_deleted:
        return {}, 202

    return {
        "errors": [
            {
                "error": "NotFound",
                "message": "That communication item does not exist.",
            }
        ]
    }, 404
