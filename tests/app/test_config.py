import importlib
import os
from unittest import mock

import pytest

from app import config
from app.config import QueueNames, str_to_bool


def cf_conf():
    os.environ["ADMIN_BASE_URL"] = "cf"


@pytest.fixture
def reload_config():
    """
    Reset config, by simply re-running config.py from a fresh environment
    """
    old_env = os.environ.copy()

    yield

    os.environ = old_env
    importlib.reload(config)


def test_load_cloudfoundry_config_if_available(monkeypatch, reload_config):
    os.environ["ADMIN_BASE_URL"] = "env"
    monkeypatch.setenv("VCAP_SERVICES", "some json blob")
    monkeypatch.setenv("VCAP_APPLICATION", "some json blob")

    with mock.patch("app.cloudfoundry_config.extract_cloudfoundry_config", side_effect=cf_conf) as cf_config:
        # reload config so that its module level code (ie: all of it) is re-instantiated
        importlib.reload(config)

    assert cf_config.called

    assert os.environ["ADMIN_BASE_URL"] == "cf"
    assert config.Config.ADMIN_BASE_URL == "cf"


def test_load_config_if_cloudfoundry_not_available(monkeypatch, reload_config):
    os.environ["ADMIN_BASE_URL"] = "env"

    monkeypatch.delenv("VCAP_SERVICES", raising=False)

    with mock.patch("app.cloudfoundry_config.extract_cloudfoundry_config") as cf_config:
        # reload config so that its module level code (ie: all of it) is re-instantiated
        importlib.reload(config)

    assert not cf_config.called

    assert os.environ["ADMIN_BASE_URL"] == "env"
    assert config.Config.ADMIN_BASE_URL == "env"


def test_queue_names_all_queues_correct():
    # Need to ensure that all_queues() only returns queue names used in API
    queues = QueueNames.all_queues()
    assert len(queues) == 14
    assert (
        set(
            [
                QueueNames.PRIORITY,
                QueueNames.BULK,
                QueueNames.PERIODIC,
                QueueNames.DATABASE,
                QueueNames.SEND_SMS,
                QueueNames.SEND_THROTTLED_SMS,
                QueueNames.SEND_EMAIL,
                QueueNames.RESEARCH_MODE,
                QueueNames.REPORTING,
                QueueNames.JOBS,
                QueueNames.RETRY,
                QueueNames.NOTIFY,
                # QueueNames.CREATE_LETTERS_PDF,
                QueueNames.CALLBACKS,
                # QueueNames.LETTERS,
                QueueNames.DELIVERY_RECEIPTS,
            ]
        )
        == set(queues)
    )


def test_when_env_value_is_a_valid_boolean(reload_config):
    os.environ["FF_REDIS_BATCH_SAVING"] = "False"
    assert str_to_bool(os.getenv("FF_REDIS_BATCH_SAVING"), True) is False

    os.environ["FF_REDIS_BATCH_SAVING"] = "True"
    assert str_to_bool(os.getenv("FF_REDIS_BATCH_SAVING"), False) is True

    assert str_to_bool("True", False) is True
    assert str_to_bool("tRuE", False) is True
    assert str_to_bool("true", False) is True
    assert str_to_bool("False", True) is False
    assert str_to_bool("false", True) is False
    assert str_to_bool("FALSE", True) is False
    assert str_to_bool("       FALSE        ", True) is False


def test_when_env_value_default_is_used(reload_config):
    os.environ["SOME_OTHER_ENV_VAR"] = "this is fine"
    assert str_to_bool(os.getenv("SOME_OTHER_ENV_VAR"), False) is False

    os.environ["FF_REDIS_BATCH_SAVING"] = "true false"
    assert str_to_bool(os.getenv("FF_REDIS_BATCH_SAVING"), True) is True

    os.environ["FF_REDIS_BATCH_SAVING"] = ""
    assert str_to_bool(os.getenv("FF_REDIS_BATCH_SAVING"), True) is True

    assert str_to_bool(os.getenv("NON_EXISTENT_ENV_VAR"), False) is False
    assert str_to_bool("mmmm cheese", True) is True
    assert str_to_bool(None, True) is True
    assert str_to_bool(None, False) is False
