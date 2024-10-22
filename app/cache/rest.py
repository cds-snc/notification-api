from flask import Blueprint, current_app, jsonify
from notifications_utils.clients.redis.cache_keys import CACHE_KEYS_ALL

from app import redis_store
from app.errors import register_errors
from app.schemas import event_schema

cache_blueprint = Blueprint("cache", __name__, url_prefix="/cache-clear")
register_errors(cache_blueprint)


@cache_blueprint.route("", methods=["POST"])
def clear():
    try:
        max(redis_store.delete_cache_keys_by_pattern(pattern) for pattern in CACHE_KEYS_ALL)
        return jsonify(result="ok"), 201
    except Exception as e:
        current_app.logger.error("Unable to clear the cache", exc_info=e)

        return jsonify({"error": "Unable to clear the cache"}), 500
