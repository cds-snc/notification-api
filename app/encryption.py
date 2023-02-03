from typing import Any, NewType, Optional, TypedDict

from flask_bcrypt import check_password_hash, generate_password_hash
from itsdangerous import URLSafeSerializer

SignedNotification = NewType("SignedNotification", str)


class NotificationDictToSign(TypedDict):
    # todo: remove duplicate keys
    id: str
    template: str  # actually template_id
    service_id: str
    template_version: int
    to: str  # recipient
    reply_to_text: Optional[str]
    personalisation: Optional[dict]
    simulated: Optional[bool]
    api_key: str
    key_type: str  # should be ApiKeyType but I can't import that here
    client_reference: Optional[str]
    sender_id: Optional[str]
    job: Optional[str]  # actually job_id
    row_number: Optional[Any]  # should this be int or str?


class CryptoSigner:
    def init_app(self, app):
        self.serializer = URLSafeSerializer(app.config.get("SECRET_KEY"))
        self.salt = app.config.get("DANGEROUS_SALT")

    def sign(self, to_sign):
        return self.serializer.dumps(to_sign, salt=self.salt)

    def verify(self, to_verify):
        return self.serializer.loads(to_verify, salt=self.salt)

    def sign_notification(self, notification: NotificationDictToSign) -> SignedNotification:
        "A wrapper around the sign fn to define the argument type and return type"
        return self.sign(notification)

    def verify_notification(self, signed_notification: SignedNotification) -> NotificationDictToSign:
        "A wrapper around the verify fn to define the argument type and return type"
        return self.verify(signed_notification)


def hashpw(password):
    return generate_password_hash(password.encode("UTF-8"), 10).decode("utf-8")


def check_hash(password, hashed_password):
    # If salt is invalid throws a 500 should add try/catch here
    return check_password_hash(hashed_password, password)
