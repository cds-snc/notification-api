from flask import jsonify

from app import api_user
from app.dao.template_categories_dao import dao_get_all_template_categories
from app.errors import InvalidRequest
from app.models import ApiKeyPermission
from app.v2.manage_template import v2_manage_template_blueprint


@v2_manage_template_blueprint.route("/template-categories", methods=["GET"])
def get_template_categories():
    if not api_user.has_permission(ApiKeyPermission.MANAGE_TEMPLATES):
        raise InvalidRequest("This API key does not have permission to manage templates.", status_code=403)

    template_categories = dao_get_all_template_categories(hidden=False)

    return (
        jsonify(
            template_categories=[
                {"template_category_id": str(template_category.id), "name": template_category.name_en}
                for template_category in template_categories
            ]
        ),
        200,
    )
