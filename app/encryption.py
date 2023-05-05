from typing import Any, List, NewType, Optional, TypedDict, cast

from flask_bcrypt import check_password_hash, generate_password_hash
from itsdangerous import BadSignature, URLSafeSerializer
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
    def init_app(self, app: Any, secret_key: str | List[str], salt: str) -> None:
        self.app = app
        self.secret_key = cast(List[str], [secret_key] if type(secret_key) is str else secret_key)
        self.serializer = URLSafeSerializer(secret_key)
        self.salt = salt
        self.dangerous_salt = app.config.get("DANGEROUS_SALT")

    def sign(self, to_sign: str | NotificationDictToSign) -> str | bytes:
        return self.serializer.dumps(to_sign, salt=self.salt)

    def sign_with_all_keys(self, to_sign: str | NotificationDictToSign) -> List[str | bytes]:
        signed = []
        for k in reversed(self.secret_key):  # reversed so that the default key is last
            signed.append(URLSafeSerializer(k).dumps(to_sign, salt=self.salt))
        return signed

    # TODO: get rid of this after everything is signed with the new salts
    # This is only needed where we look things up by the signed value:
    #     - get_api_key_by_secret()
    def sign_dangerous(self, to_sign: str) -> str | bytes:
        return self.serializer.dumps(to_sign, salt=self.dangerous_salt)

    def sign_dangerous_with_all_keys(self, to_sign: str | NotificationDictToSign) -> List[str | bytes]:
        signed = []
        for k in reversed(self.secret_key):  # reversed so that the default key is last
            signed.append(URLSafeSerializer(k).dumps(to_sign, salt=self.dangerous_salt))
        return signed

    # NOTE: currently the verify checks against the default salt as well as the dangerous salt
    # TODO: remove this double check once we've removed DANGEROUS_SALT
    def verify(self, to_verify: str | bytes) -> Any:
        try:
            return self.serializer.loads(to_verify, salt=self.salt)
        except BadSignature:
            return self.serializer.loads(to_verify, salt=self.dangerous_salt)

    # This ignores the signature so should be used with caution
    def verify_unsafe(self, to_verify: str | bytes) -> Any:
        return self.serializer.loads_unsafe(to_verify, salt=self.dangerous_salt)[1]


def hashpw(password):
    return generate_password_hash(password.encode("UTF-8"), 10).decode("utf-8")


def check_hash(password, hashed_password):
    # If salt is invalid throws a 500 should add try/catch here
    return check_password_hash(hashed_password, password)
