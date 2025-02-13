import pytest
from itsdangerous.exc import BadSignature

from app import signer_notification
from app.annotations import sign_return, unsign_params
from app.encryption import CryptoSigner, SignedNotification, SignedNotifications


class TestUnsignParamsAnnotation:
    @pytest.fixture(scope="class", autouse=True)
    def setup_class(self, notify_api):
        # We just want to setup the notify_api flask app for tests within the class.
        pass

    def test_unsign_with_bad_signature_notification(self, notify_api):
        @unsign_params
        def annotated_unsigned_function(
            signed_notification: SignedNotification,
        ) -> str:
            return signed_notification

        custom_signer = CryptoSigner()
        custom_signer.init_app(notify_api, "shhhhh", "salty")

        signed = custom_signer.sign("raw notification")
        with pytest.raises(BadSignature):
            annotated_unsigned_function(signed)

    def test_unsign_with_one_signed_notification(self):
        @unsign_params
        def func_with_one_signed_notification(
            signed_notification: SignedNotification,
        ) -> str:
            return signed_notification

        signed = signer_notification.sign("raw notification")
        unsigned = func_with_one_signed_notification(signed)
        assert unsigned == "raw notification"

    def test_unsign_with_non_SignedNotification_parameter(self):
        def func_with_one_signed_notification(signed_notification: str):
            return signed_notification

        signed = "raw notification"
        unsigned = func_with_one_signed_notification(signed)
        assert unsigned == "raw notification"

    def test_unsign_with_list_of_signed_notifications(self):
        @unsign_params
        def func_with_list_of_signed_notifications(
            signed_notifications: SignedNotifications,
        ):
            return signed_notifications

        signed = [signer_notification.sign(notification) for notification in ["raw notification 1", "raw notification 2"]]
        unsigned = func_with_list_of_signed_notifications(signed)
        assert unsigned == ["raw notification 1", "raw notification 2"]

    def test_unsign_with_empty_list_of_signed_notifications(self):
        @unsign_params
        def func_with_list_of_signed_notifications(
            signed_notifications: SignedNotifications,
        ):
            return signed_notifications

        signed = []
        unsigned = func_with_list_of_signed_notifications(signed)
        assert unsigned == []

    def test_sign_return(self):
        @sign_return
        def func_to_sign_return():
            return "raw notification"

        signed = func_to_sign_return()
        assert signer_notification.verify(signed) == "raw notification"

    def test_sign_return_with_list(self):
        @sign_return
        def func_to_sign_return():
            return ["raw notification 1", "raw notification 2"]

        signed = func_to_sign_return()
        assert [signer_notification.verify(notification) for notification in signed] == [
            "raw notification 1",
            "raw notification 2",
        ]

    def test_sign_return_with_empty_list(self):
        @sign_return
        def func_to_sign_return():
            return []

        signed = func_to_sign_return()
        assert signed == []

    def test_sign_return_with_non_string_return(self):
        @sign_return
        def func_to_sign_return():
            return 1

        signed = func_to_sign_return()
        assert signed == 1
