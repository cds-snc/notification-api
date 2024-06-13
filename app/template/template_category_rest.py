from flask import Blueprint, jsonify, request

from app.dao.template_categories_dao import (
    dao_create_template_category,
    dao_get_all_template_categories,
    dao_get_template_category_by_id,
    dao_update_template_category,
)
from app.models import TemplateCategory
from app.schemas import template_category_schema

template_category_blueprint = Blueprint(
    "template_category",
    __name__,
    url_prefix="template/category",
)


@template_category_blueprint.route("", methods=["POST"])
def create_template_category():
    data = request.get_json()

    template_category_schema.load(data)
    template_category = TemplateCategory.from_json(data)

    dao_create_template_category(template_category)

    return jsonify(data=template_category_schema.dump(template_category)), 201


@template_category_blueprint.route("/<template_category_id>", methods=["POST"])
def update_template_category(template_category_id):
    request_json = request.get_json()
    update_dict = template_category_schema.load(request_json)

    category_to_update = dao_get_template_category_by_id(template_category_id)

    for key in request_json:
        setattr(category_to_update, key, update_dict[key])

    dao_update_template_category(category_to_update)

    return jsonify(data=category_to_update.serialize()), 200


@template_category_blueprint.route("", methods=["GET"])
def get_template_categories():
    template_categories = dao_get_all_template_categories()
    return jsonify(data=template_category_schema.dump(template_categories, many=True)), 200
