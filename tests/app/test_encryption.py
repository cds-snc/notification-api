from datetime import datetime, timezone

import pytest
from itsdangerous import BadSignature

from app.encryption import (
    CryptoSigner,
    create_notification_envelope,
    update_notification_envelope,
    verify_notification,
)


@pytest.fixture()
def crypto_signer(notify_api):
    signer = CryptoSigner()
    signer.init_app(notify_api, "secret", "salt")
    yield signer


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
        assert signer12.sign_with_all_keys("this") == [
            signer2.sign("this"),
            signer1.sign("this"),
        ]

    def test_notification_envelope_round_trip_preserves_unknown_metadata(self, crypto_signer):
        envelope = create_notification_envelope(
            {
                "template": "template-id",
                "template_version": 1,
                "to": "test@example.com",
                "personalisation": None,
                "api_key": "api-key-id",
                "key_type": "normal",
                "queue": None,
                "sender_id": None,
                "client_reference": None,
                "row_number": None,
            },
            enqueued_at=datetime(2026, 10, 7, 14, 30, tzinfo=timezone.utc),
        )
        envelope["metadata"]["future_attribute"] = {"nested": [1, True, None]}  # type: ignore[typeddict-unknown-key]

        updated = update_notification_envelope(
            envelope,
            last_processed_at=datetime(2026, 10, 7, 14, 35, tzinfo=timezone.utc),
            retry_count=1,
        )
        message, verified_envelope = verify_notification(crypto_signer, crypto_signer.sign(updated))

        assert message == envelope["message"]
        assert verified_envelope == updated
        assert verified_envelope["metadata"] == {
            "enqueued_at": "2026-10-07T14:30:00Z",
            "last_processed_at": "2026-10-07T14:35:00Z",
            "retry_count": 1,
            "future_attribute": {"nested": [1, True, None]},
        }
        assert envelope["metadata"]["last_processed_at"] is None
        assert envelope["metadata"]["retry_count"] == 0

    def test_verify_notification_accepts_legacy_signed_dictionary(self, crypto_signer):
        notification = {"id": "notification-id"}

        message, envelope = verify_notification(crypto_signer, crypto_signer.sign(notification))

        assert message == notification
        assert envelope is None
