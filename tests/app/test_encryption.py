import pytest
from itsdangerous import BadSignature

from app.encryption import CryptoSigner


def test_sign_and_verify(notify_api):
    signer = CryptoSigner()
    signer.init_app(notify_api, "secret", "salt")
    signed = signer.sign("this")
    assert signed != "this"
    assert signer._verify(signed) == "this"


def test_should_verify_content_signed_with_DANGEROUS_SALT(notify_api):
    signer = CryptoSigner()
    signer.init_app(notify_api, "secret", "salt")
    signed = signer.sign_dangerous("this")
    assert signer._verify(signed) == "this"


def should_not_verify_content_signed_with_different_secrets(notify_api):
    signer1 = CryptoSigner()
    signer2 = CryptoSigner()
    signer1.init_app(notify_api, "secret1", "salt")
    signer2.init_app(notify_api, "secret2", "salt")
    with pytest.raises(BadSignature):
        signer2.verify(signer1.sign("this"))


def should_not_verify_content_signed_with_different_salts(notify_api):
    signer1 = CryptoSigner()
    signer2 = CryptoSigner()
    signer1.init_app(notify_api, "secret", "salt1")
    signer2.init_app(notify_api, "secret", "salt2")

    with pytest.raises(BadSignature):
        signer2.verify(signer1.sign("this"))


def test_should_sign_json(notify_api):
    signer = CryptoSigner()
    signer.init_app(notify_api, "secret", "salt")
    assert signer.verify(signer.sign({"this": "that"})) == {"this": "that"}
