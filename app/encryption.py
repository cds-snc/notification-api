from typing import Any, NewType, Optional, TypedDict

from flask_bcrypt import check_password_hash, generate_password_hash
from itsdangerous import URLSafeSerializer
from typing_extensions import NotRequired  # type: ignore

SignedNotification = NewType("SignedNotification", str)


class NotificationDictToSign(TypedDict):
    id: NotRequired[str]
    template: str  # actually template_id
    service_id: NotRequired[str]
    template_version: int
    to: str  # recipient
    reply_to_text: NotRequired[str]  # should this be NotRequired?
    personalisation: Optional[dict]
    simulated: NotRequired[bool]
    api_key: str
    key_type: str  # should be ApiKeyType but I can't import that here
    client_reference: Optional[str]
    queue: Optional[str]
    sender_id: NotRequired[str]
    job: NotRequired[str]  # actually job id
    row_number: Optional[Any]  # should figure out what this is


class CryptoSigner:
    def init_app(self, app):
        self.serializer = URLSafeSerializer(app.config.get("SECRET_KEY"))
        self.salt = app.config.get("DANGEROUS_SALT")

    def sign(self, to_sign):
        return self.serializer.dumps(to_sign, salt=self.salt)

    def verify(self, to_verify):
        return self.serializer.loads(to_verify, salt=self.salt)

    def sign_notification(self, notification: NotificationDictToSign) -> SignedNotification:
        return self.sign(notification)

    def verify_notification(self, signed_notification: SignedNotification) -> NotificationDictToSign:
        return self.verify(signed_notification)


def hashpw(password):
    return generate_password_hash(password.encode("UTF-8"), 10).decode("utf-8")


def check_hash(password, hashed_password):
    # If salt is invalid throws a 500 should add try/catch here
    return check_password_hash(hashed_password, password)
