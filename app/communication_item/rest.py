from flask import Blueprint, jsonify

from app.dao import communication_item_dao
from app.errors import register_errors
from app.schemas import communication_item_schema

communication_item_blueprint = Blueprint(
    'communication_item',
    __name__,
    url_prefix='/communication-item'
)

register_errors(communication_item_blueprint)


@communication_item_blueprint.route('', methods=['GET'])
def get_communication_items():
    communication_items = communication_item_dao.get_communication_items()
    return jsonify(data=communication_item_schema.dump(communication_items, many=True).data)
