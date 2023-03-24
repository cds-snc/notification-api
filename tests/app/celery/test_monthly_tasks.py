from itsdangerous import URLSafeSerializer

from app.celery.monthly_tasks import (
    resign_api_keys_task,
    resign_inbound_sms_task,
    resign_service_callbacks_task,
)
from app.models import ApiKey, InboundSms, ServiceCallbackApi
from tests.app.db import create_api_key, create_inbound_sms, create_service_callback_api


class TestResigning:
    def test_resign_callbacks(self, sample_service):
        from app import signer_bearer_token

        signer_bearer_token.serializer = URLSafeSerializer(["k1", "k2"])
        initial_callback = create_service_callback_api(service=sample_service)
        bearer_token = initial_callback.bearer_token
        _bearer_token = initial_callback._bearer_token

        signer_bearer_token.serializer = URLSafeSerializer(["k2", "k3"])
        resign_service_callbacks_task()

        callback = ServiceCallbackApi.query.get(initial_callback.id)
        assert callback.bearer_token == bearer_token
        assert callback._bearer_token != _bearer_token

    def test_resign_api_keys(self, sample_service):
        from app import signer_api_key

        signer_api_key.serializer = URLSafeSerializer(["k1", "k2"])
        initial_key = create_api_key(service=sample_service)
        secret = initial_key.secret
        _secret = initial_key._secret

        signer_api_key.serializer = URLSafeSerializer(["k2", "k3"])
        resign_api_keys_task()

        api_key = ApiKey.query.get(initial_key.id)
        assert api_key.secret == secret
        assert api_key._secret != _secret


def test_resign_inbound_sms(self, sample_service):
    from app import signer_inbound_sms

    signer_inbound_sms.serializer = URLSafeSerializer(["k1", "k2"])
    initial_sms = create_inbound_sms(service=sample_service)
    content = initial_sms.content
    _content = initial_sms._content

    signer_inbound_sms.serializer = URLSafeSerializer(["k2", "k3"])
    resign_inbound_sms_task()

    sms = InboundSms.query.get(initial_sms.id)
    assert sms.content == content
    assert sms._content != _content
