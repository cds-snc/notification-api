from unittest.mock import patch
from app.celery.monthly_tasks import (
    resign_api_keys_task, resign_service_callbacks_task,
)
from app.models import  ServiceCallbackApi, ApiKey
from tests.app.db import (
    create_service_callback_api, create_api_key
)
from itsdangerous import URLSafeSerializer


class TestResigning():
    def test_resign_callbacks(self, sample_service):
        from app import signer

        signer.serializer = URLSafeSerializer(["k1", "k2"])

        initial_callback = create_service_callback_api(service=sample_service)
        bearer_token = initial_callback.bearer_token
        _bearer_token = initial_callback._bearer_token

        signer.serializer = URLSafeSerializer(["k2", "k3"])
        resign_service_callbacks_task()
        
        callback = ServiceCallbackApi.query.get(initial_callback.id)
        assert callback.bearer_token == bearer_token
        assert callback._bearer_token != _bearer_token
        
    def test_resign_api_keys(client, sample_service):
        from app import signer
        
        signer.serializer = URLSafeSerializer(["k1", "k2"])

        initial_key = create_api_key(service=sample_service)
        secret = initial_key.secret
        _secret = initial_key._secret

        signer.serializer = URLSafeSerializer(["k2", "k3"])
        resign_api_keys_task()
        
        api_key = ApiKey.query.get(initial_key.id)
        assert api_key.secret == secret
        assert api_key._secret != _secret
