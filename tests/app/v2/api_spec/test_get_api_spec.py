import os

import pytest
from flask import Flask

from app.v2.api_spec.get_api_spec import v2_api_spec_blueprint


@pytest.fixture
def client():
    app = Flask(__name__)
    app.register_blueprint(v2_api_spec_blueprint)
    app.config["TESTING"] = True
    app.root_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../.."))
    with app.test_client() as client:
        yield client


def test_get_api_spec_en(client):
    response = client.get("/v2/api-spec?lang=en")
    assert response.status_code == 200
    assert response.mimetype == "application/yaml"
    assert b"openapi:" in response.data


def test_get_api_spec_fr(client):
    response = client.get("/v2/api-spec?lang=fr")
    assert response.status_code == 200
    assert response.mimetype == "application/yaml"
    assert b"openapi:" in response.data
    assert b"API de Notifications" in response.data


def test_get_api_spec_default_lang(client):
    response = client.get("/v2/api-spec")
    assert response.status_code == 200
    assert response.mimetype == "application/yaml"
    assert b"openapi:" in response.data


def test_get_api_spec_invalid_lang(client):
    response = client.get("/v2/api-spec?lang=es")
    assert response.status_code == 400
    assert response.is_json
    assert response.get_json()["error"] == "Language not supported"
