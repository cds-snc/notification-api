import os
from functools import wraps

from flask import current_app, jsonify

from app.models import User

EMAIL_PREFIX = os.getenv("CYPRESS_USER_EMAIL_PREFIX", "notify-ui-tests+ag_")


def fetch_cypress_user_by_id(func):
    """A simple decorator to fetch a user by id and pass it to the decorated function.
    Useful to reduce boilerplate in the Cypress REST routes that delete by user id.
    """

    @wraps(func)
    def wrapper(user_id, *args, **kwargs):
        user = User.query.filter_by(id=user_id).first()

        if not user:
            current_app.logger.error(f"Error: No user found with id {user_id}")
            return jsonify({"error": f"User id {user_id} not found"}), 404

        return func(user_id, user, *args, **kwargs)  # Pass user instead of email_name

    return wrapper
