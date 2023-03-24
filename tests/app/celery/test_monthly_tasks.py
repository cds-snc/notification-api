from itsdangerous import URLSafeSerializer

from app.celery.monthly_tasks import resign_api_keys_task, resign_service_callbacks_task, resign_inbound_sms_task
from app.models import ApiKey, ServiceCallbackApi, InboundSms
from tests.app.db import create_api_key, create_service_callback_api, create_inbound_sms
from app import signer


class TestResigning:
    def test_resign_callbacks(self, sample_service):
        signer.serializer = URLSafeSerializer(["k1", "k2"])
        initial_callback = create_service_callback_api(service=sample_service)
        bearer_token = initial_callback.bearer_token
        _bearer_token = initial_callback._bearer_token

        signer.serializer = URLSafeSerializer(["k2", "k3"])
        resign_service_callbacks_task()

        callback = ServiceCallbackApi.query.get(initial_callback.id)
        assert callback.bearer_token == bearer_token
        assert callback._bearer_token != _bearer_token

    def test_resign_api_keys(self, sample_service):
        signer.serializer = URLSafeSerializer(["k1", "k2"])
        initial_key = create_api_key(service=sample_service)
        secret = initial_key.secret
        _secret = initial_key._secret

        signer.serializer = URLSafeSerializer(["k2", "k3"])
        resign_api_keys_task()

        api_key = ApiKey.query.get(initial_key.id)
        assert api_key.secret == secret
        assert api_key._secret != _secret

def test_resign_inbound_sms(self, sample_service):
        signer.serializer = URLSafeSerializer(["k1", "k2"])
        initial_sms = create_inbound_sms(service=sample_service)
        content = initial_sms.content
        _content = initial_sms._content

        signer.serializer = URLSafeSerializer(["k2", "k3"])
        resign_inbound_sms_task()

        sms = InboundSms.query.get(sms.id)
        assert sms.content == content
        assert sms._content != _content
