from typing import Any, NewType, Optional, TypedDict

from flask_bcrypt import check_password_hash, generate_password_hash
from itsdangerous import URLSafeSerializer, BadSignature
from typing_extensions import NotRequired  # type: ignore

SignedNotification = NewType("SignedNotification", str)


class NotificationDictToSign(TypedDict):
    # todo: remove duplicate keys
    # todo: remove all NotRequired and decide if key should be there or not
    id: NotRequired[str]
    template: str  # actually template_id
    service_id: NotRequired[str]
    template_version: int
    to: str  # recipient
    reply_to_text: NotRequired[str]
    personalisation: Optional[dict]
    simulated: NotRequired[bool]
    api_key: str
    key_type: str  # should be ApiKeyType but I can't import that here
    client_reference: Optional[str]
    queue: Optional[str]
    sender_id: NotRequired[str]
    job: NotRequired[str]  # actually job_id
    row_number: Optional[Any]  # should this be int or str?


class CryptoSigner:
    def init_app(self, app):
        self.serializer = URLSafeSerializer(app.config.get("SECRET_KEY"))
        self.salt = app.config.get("DANGEROUS_SALT")

    def sign(self, to_sign: Any, salt: Optional[str] = None) -> str:
        if salt is None:
            salt = self.salt
        return self.serializer.dumps(to_sign, salt=salt)

    def verify(self, to_verify: str, salt: Optional[str] = None) -> Any:
        if salt is None:
            salt = self.salt
        try:
            return self.serializer.loads(to_verify, salt=salt)
        except BadSignature:
            return self.serializer.loads(to_verify, salt=self.salt)

    def sign_notification(self, notification: NotificationDictToSign) -> SignedNotification:
        "A wrapper around the sign fn to define the argument type and return type"
        return self.sign(notification, "notification")

    def verify_notification(self, signed_notification: SignedNotification) -> NotificationDictToSign:
        "A wrapper around the verify fn to define the argument type and return type"
        return self.verify(signed_notification, "notification")

    def sign_personalisation(self, personalisation: dict) -> str:
        return self.sign(personalisation, "personalisation")
    
    def verify_personalisation(self, signed_personalisation: str) -> dict:
        return self.verify(signed_personalisation, "personalisation")
    
    def sign_complaint(self, complaint: dict) -> str:
        return self.sign(complaint, "complaint")
    
    def verify_complaint(self, signed_complaint: str) -> dict:
        return self.verify(signed_complaint, "complaint")
    
    def sign_delivery_status(self, delivery_status: dict) -> str:
        return self.sign(delivery_status, "delivery-status")
    
    def verify_delivery_status(self, signed_delivery_status: str) -> dict:
        return self.verify(signed_delivery_status, "delivery-status")
    
    def sign_bearer_token(self, bearer_token: str) -> str:
        return self.sign(bearer_token, "bearer-token")

    def verify_bearer_token(self, signed_bearer_token: str) -> str:
        return self.verify(signed_bearer_token, "bearer-token")
    
    def sign_api_key(self, api_key_secret: str) -> str:
        return self.sign(api_key_secret, "api-key")
    
    def verify_api_key(self, signed_api_key_secret: str) -> str:
        return self.verify(signed_api_key_secret, "api-key")
    
    def sign_inbound_sms(self, content: str) -> str:
        return self.sign(content, "inbound-sms")
    
    def verify_inbound_sms(self, signed_content: str) -> str:
        return self.verify(signed_content, "inbound-sms")


def hashpw(password):
    return generate_password_hash(password.encode("UTF-8"), 10).decode("utf-8")


def check_hash(password, hashed_password):
    # If salt is invalid throws a 500 should add try/catch here
    return check_password_hash(hashed_password, password)
