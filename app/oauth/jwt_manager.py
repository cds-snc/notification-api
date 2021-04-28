from flask_jwt_extended import JWTManager

from app.dao.users_dao import get_user_by_id
from app.models import User

jwt = JWTManager()


@jwt.user_identity_loader
def transform_user_to_identity_for_jwt(user: User):
    return {
        'id': user.id,
        'name': user.name,
        'email_address': user.email_address,
        'services': [x.id for x in user.services if x.active]
    }


@jwt.user_lookup_loader
def transform_jwt_to_user(_jwt_header, jwt_data) -> User:
    sub = jwt_data['sub']
    return get_user_by_id(user_id=sub['id'])
