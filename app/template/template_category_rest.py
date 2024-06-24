from flask import Blueprint, jsonify, request

from app.dao.template_categories_dao import (
    dao_create_template_category,
    dao_delete_template_category_by_id,
    dao_get_all_template_categories,
    dao_get_template_category_by_id,
    dao_get_template_category_by_template_id,
    dao_update_template_category,
)
from app.errors import register_errors
from app.models import TemplateCategory
from app.schemas import template_category_schema

template_category_blueprint = Blueprint(
    "template_category",
    __name__,
    url_prefix="/template/category",
)

register_errors(template_category_blueprint)


@template_category_blueprint.route("", methods=["POST"])
def create_template_category():
    data = request.get_json()

    template_category_schema.load(data)
    template_category = TemplateCategory.from_json(data)

    dao_create_template_category(template_category)

    return jsonify(template_category=template_category_schema.dump(template_category)), 201


@template_category_blueprint.route("/<uuid:template_category_id>", methods=["GET"])
def get_template_category(template_category_id):
    template_category = dao_get_template_category_by_id(template_category_id)
    return jsonify(template_category=template_category_schema.dump(template_category)), 200


@template_category_blueprint.route("/by-template-id/<uuid:template_id>", methods=["GET"])
def get_template_category_by_template_id(template_id):
    template_category = dao_get_template_category_by_template_id(template_id)
    return jsonify(template_category=template_category_schema.dump(template_category)), 200


@template_category_blueprint.route("", methods=["GET"])
def get_template_categories():
    template_type = request.args.get("template_type", None)

    hidden = request.args.get("hidden")
    if hidden is not None:
        if hidden == "True":
            hidden = True
        elif hidden == "False":
            hidden = False
        else:
            hidden = None

    # Validate request args
    if template_type is not None:
        if template_type not in ["sms", "email"]:
            return jsonify(message="Invalid filter 'template_type', valid template_types: 'sms', 'email'"), 400

    template_categories = template_category_schema.dump(dao_get_all_template_categories(template_type, hidden), many=True)
    return jsonify(template_categories=template_categories), 200


@template_category_blueprint.route("/<uuid:template_category_id>", methods=["POST"])
def update_template_category(template_category_id):
    current_category = dict(template_category_schema.dump(dao_get_template_category_by_id(template_category_id)))
    current_category.update(request.get_json())

    updated_category = template_category_schema.load(current_category)
    dao_update_template_category(updated_category)

    return jsonify(template_category=template_category_schema.dump(updated_category)), 200


@template_category_blueprint.route("/<uuid:template_category_id>", methods=["DELETE"])
def delete_template_category(template_category_id):
    """Deletes a template category. By default, if the template category is associated with any template, it will not be deleted.
    This can be overriden by specifying the `cascade` query parameter.

    Args:
        template_category_id (str): The id of the template_category to delete

    Request Args:
        cascade (bool, optional): Specify whether to dissociate the category from templates that use it to force removal. Defaults to False.

    Returns:
        (flask.Response): The response message and http status code.
    """

    if request.args.get("cascade") == "True":
        dao_delete_template_category_by_id(template_category_id, cascade=True)
        return "", 200

    template_category = dao_get_template_category_by_id(template_category_id)
    if len(template_category.templates) > 0:
        return jsonify(message="Cannot delete a template category with templates assigned to it."), 400
    else:
        dao_delete_template_category_by_id(template_category_id)
    return "", 200
