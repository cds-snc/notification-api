from unittest.mock import patch

from flask import url_for
from notifications_utils.clients.redis.cache_keys import CACHE_KEYS_ALL

from tests import create_cache_clear_authorization_header


class TestCacheClear:
    def test_clear_cache_success(self, client):
        with patch("app.redis_store.delete_cache_keys_by_pattern", return_value=1) as mock_delete:
            auth_header = create_cache_clear_authorization_header()
            response = client.post(
                url_for("cache.clear"),
                headers=[("Content-Type", "application/json"), auth_header],
            )
            assert response.status_code == 201
            assert response.json == {"result": "ok"}
            assert mock_delete.call_count == len(CACHE_KEYS_ALL)

    def test_clear_cache_failure(self, client):
        with patch("app.redis_store.delete_cache_keys_by_pattern", side_effect=Exception("Redis error")) as mock_delete:
            auth_header = create_cache_clear_authorization_header()
            response = client.post(
                url_for("cache.clear"),
                headers=[("Content-Type", "application/json"), auth_header],
            )
            assert response.status_code == 500
            assert response.json == {"error": "Unable to clear the cache"}
            assert mock_delete.call_count == 1
