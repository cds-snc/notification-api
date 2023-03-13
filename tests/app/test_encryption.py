import pytest
from itsdangerous import BadSignature

from app.encryption import CryptoSigner

signer = CryptoSigner()


def test_should_sign_content(notify_api):
    signer.init_app(notify_api)
    assert signer._sign("this") != "this"


def test_sign_default(notify_api):
    signer.init_app(notify_api)
    signed = signer._sign("this")
    assert signer._verify(signed) == "this"


def test_sign_with_salt(notify_api):
    signer.init_app(notify_api)
    signed = signer._sign("this", "salt")
    assert signer._verify(signed, "salt") == "this"


def test_should_verify_content_signed_with_DANGEROUS_SALT(notify_api):
    signer.init_app(notify_api)
    signed = signer.sign_dangerous("this")
    assert signer._verify(signed, "salt") == "this"


def should_not_verify_content_signed_with_different_salts(notify_api):
    signer.init_app(notify_api)
    signed = signer.sign("this", "salt")
    with pytest.raises(BadSignature):
        signer.verify(signed, "different-salt")


def test_should_sign_json(notify_api):
    signer.init_app(notify_api)
    signed = signer.sign({"this": "that"})
    assert signer.verify(signed) == {"this": "that"}


def test_sign_notification(notify_api):
    signer.init_app(notify_api)
    signed = signer.sign_notification({"this": "that"})
    assert signer.verify_notification(signed) == {"this": "that"}


def test_sign_personalisation(notify_api):
    signer.init_app(notify_api)
    signed = signer.sign_personalisation({"this": "that"})
    assert signer.verify_personalisation(signed) == {"this": "that"}


def test_sign_complaint(notify_api):
    signer.init_app(notify_api)
    signed = signer.sign_complaint({"this": "that"})
    assert signer.verify_complaint(signed) == {"this": "that"}


def test_sign_delivery_status(notify_api):
    signer.init_app(notify_api)
    signed = signer.sign_delivery_status({"this": "that"})
    assert signer.verify_delivery_status(signed) == {"this": "that"}


def test_sign_api_key(notify_api):
    signer.init_app(notify_api)
    signed = signer.sign_api_key("this")
    assert signer.verify_api_key(signed) == "this"


def test_sign_bearer_token(notify_api):
    signer.init_app(notify_api)
    signed = signer.sign_bearer_token("this")
    assert signer.verify_bearer_token(signed) == "this"


def test_inbould_sms(notify_api):
    signer.init_app(notify_api)
    signed = signer.sign_inbound_sms("this")
    assert signer.verify_inbound_sms(signed) == "this"
