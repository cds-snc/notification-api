import pytest
from itsdangerous import BadSignature

from app.encryption import CryptoSigner


class TestEncryption:
    def test_sign_and_verify(self, notify_api):
        signer = CryptoSigner()
        signer.init_app(notify_api, "secret", "salt")
        signed = signer.sign("this")
        assert signed != "this"
        assert signer.verify(signed) == "this"

    def test_should_not_verify_content_signed_with_different_secrets(self, notify_api):
        signer1 = CryptoSigner()
        signer2 = CryptoSigner()
        signer1.init_app(notify_api, "secret1", "salt")
        signer2.init_app(notify_api, "secret2", "salt")
        with pytest.raises(BadSignature):
            signer2.verify(signer1.sign("this"))

    def test_should_not_verify_content_signed_with_different_salts(self, notify_api):
        signer1 = CryptoSigner()
        signer2 = CryptoSigner()
        signer1.init_app(notify_api, "secret", "salt1")
        signer2.init_app(notify_api, "secret", "salt2")
        with pytest.raises(BadSignature):
            signer2.verify(signer1.sign("this"))

    def test_should_sign_dicts(self, notify_api):
        signer = CryptoSigner()
        signer.init_app(notify_api, "secret", "salt")
        assert signer.verify(signer.sign({"this": "that"})) == {"this": "that"}

    def test_should_verify_content_signed_with_an_old_secret(self, notify_api):
        signer1 = CryptoSigner()
        signer2 = CryptoSigner()
        signer1.init_app(notify_api, ["s1", "s2"], "salt")
        signer2.init_app(notify_api, ["s2", "s3"], "salt")
        assert signer2.verify(signer1.sign("this")) == "this"

    def test_should_unsafe_verify_content_signed_with_different_secrets(self, notify_api):
        signer1 = CryptoSigner()
        signer2 = CryptoSigner()
        signer1.init_app(notify_api, "secret1", "salt")
        signer2.init_app(notify_api, "secret2", "salt")
        assert signer2.verify_unsafe(signer1.sign("this")) == "this"

    def test_sign_with_all_keys(self, notify_api):
        signer1 = CryptoSigner()
        signer1.init_app(notify_api, "s1", "salt")
        signer2 = CryptoSigner()
        signer2.init_app(notify_api, "s2", "salt")
        signer12 = CryptoSigner()
        signer12.init_app(notify_api, ["s1", "s2"], "salt")
        assert signer12.sign_with_all_keys("this") == [signer2.sign("this"), signer1.sign("this")]
