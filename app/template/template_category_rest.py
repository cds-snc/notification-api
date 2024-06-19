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
from app.models import Template, TemplateCategory
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


@template_category_blueprint.route("<uuid:template_category_id>", methods=["GET"])
def get_template_category(template_category_id=None):
    template_category = dao_get_template_category_by_id(template_category_id)
    return jsonify(template_category=template_category_schema.dump(template_category)), 200


@template_category_blueprint.route("<uuid:template_id>", methods=["GET"])
def get_template_category_by_template_id(template_id):
    template_category = dao_get_template_category_by_template_id(template_id)
    return jsonify(template_category=template_category_schema.dump(template_category)), 200


@template_category_blueprint.route("", methods=["GET"])
def get_template_categories():
    template_categories = template_category_schema.dump(dao_get_all_template_categories(), many=True)
    return jsonify(template_categories=template_categories), 200


@template_category_blueprint.route("/<uuid:template_category_id>", methods=["POST"])
def update_template_category(template_category_id):
    request_json = request.get_json()
    update_dict = template_category_schema.load(request_json)

    category_to_update = dao_get_template_category_by_id(template_category_id)

    for key in request_json:
        setattr(category_to_update, key, update_dict[key])

    dao_update_template_category(category_to_update)

    return jsonify(template_category=category_to_update.dump()), 200


@template_category_blueprint.route("/<uuid:template_category_id>", methods=["DELETE"])
def delete_template_category(template_category_id):
    cascade = request.args.get("cascade", False)

    if not cascade:
        templates = Template.query.filter_by(template_category_id=template_category_id).one()
        if templates:
            return jsonify(message="Cannot delete template category with templates assigned to it"), 400

    dao_delete_template_category_by_id(template_category_id, cascade)

    return "", 204
