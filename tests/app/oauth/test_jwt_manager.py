from flask_jwt_extended import create_access_token, decode_token
from datetime import datetime, timedelta

from app.model import User


def test_access_token_expires_in_one_hour(notify_api, notify_db_session):
    jwt_token = create_access_token(identity=User())

    decoded_token = decode_token(jwt_token)

    expiration = datetime.fromtimestamp(decoded_token['exp'])
    issued_at = datetime.fromtimestamp(decoded_token['iat'])

    assert expiration - issued_at == timedelta(hours=1)
