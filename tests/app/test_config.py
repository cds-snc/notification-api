import importlib
import os
import subprocess
from pathlib import Path

import pytest
from flask import Flask
from sqlalchemy.pool import NullPool

from app import config, create_app, db
from app.config import QueueNames


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


def test_queue_names_all_queues_correct():
    # Need to ensure that all_queues() only returns queue names used in API
    queues = QueueNames.all_queues()
    assert len(queues) == 22
    assert set(
        [
            QueueNames.PRIORITY,
            QueueNames.BULK,
            QueueNames.PERIODIC,
            QueueNames.NIGHTLY,
            QueueNames.PRIORITY_DATABASE,
            QueueNames.NORMAL_DATABASE,
            QueueNames.BULK_DATABASE,
            QueueNames.SEND_SMS_HIGH,
            QueueNames.SEND_SMS_MEDIUM,
            QueueNames.SEND_SMS_LOW,
            QueueNames.SEND_THROTTLED_SMS,
            QueueNames.SEND_EMAIL_HIGH,
            QueueNames.SEND_EMAIL_MEDIUM,
            QueueNames.SEND_EMAIL_LOW,
            QueueNames.RESEARCH_MODE,
            QueueNames.REPORTING,
            QueueNames.JOBS,
            QueueNames.RETRY,
            QueueNames.CALLBACKS_RETRY,
            QueueNames.NOTIFY,
            # QueueNames.CREATE_LETTERS_PDF,
            QueueNames.CALLBACKS,
            # QueueNames.LETTERS,
            QueueNames.DELIVERY_RECEIPTS,
        ]
    ) == set(queues)


@pytest.mark.parametrize(
    "task_name",
    ["delete-sms-notifications", "delete-email-notifications", "delete-letter-notifications", "delete-inbound-sms"],
)
def test_cleanup_tasks_use_nightly_queue(task_name):
    assert config.Config.CELERYBEAT_SCHEDULE[task_name]["options"]["queue"] == QueueNames.NIGHTLY


@pytest.mark.parametrize("script_name", ["run_celery.sh", "run_celery_core_tasks.sh"])
def test_general_workers_do_not_consume_periodic_tasks(script_name):
    script = Path(__file__).resolve().parents[2] / "scripts" / script_name
    result = subprocess.run(
        ["sh", "-c", 'celery() { printf "%s\\n" "$@"; }; . "$1"', "test", str(script)],
        check=True,
        capture_output=True,
        text=True,
    )
    queues = result.stdout.splitlines()[-1].split(",")

    assert QueueNames.PERIODIC not in queues
    assert QueueNames.NIGHTLY not in queues
    assert QueueNames.NORMAL in queues


def test_get_safe_config(mocker, reload_config):
    mock_get_class_attrs = mocker.patch("notifications_utils.logging.get_class_attrs")
    mock_get_sensitive_config = mocker.patch("app.config.Config.get_sensitive_config")

    config.Config.get_safe_config()
    assert mock_get_class_attrs.called
    assert mock_get_sensitive_config.called


def test_get_sensitive_config():
    sensitive_config = config.Config.get_sensitive_config()
    assert sensitive_config
    for key in sensitive_config:
        assert key


def test_sqlalchemy_disable_pool_sets_null_pool(monkeypatch, reload_config):
    monkeypatch.setenv("SQLALCHEMY_DISABLE_POOL", "true")
    importlib.reload(config)

    assert config.Config.SQLALCHEMY_DISABLE_POOL is True
    assert config.Config.SQLALCHEMY_ENGINE_OPTIONS["poolclass"].__name__ == "NullPool"
    assert "pool_size" not in config.Config.SQLALCHEMY_ENGINE_OPTIONS


def test_sqlalchemy_disable_pool_default_false(monkeypatch, reload_config):
    monkeypatch.delenv("SQLALCHEMY_DISABLE_POOL", raising=False)
    importlib.reload(config)

    assert config.Config.SQLALCHEMY_DISABLE_POOL is False
    assert config.Config.SQLALCHEMY_ENGINE_OPTIONS["pool_recycle"] == 300
    assert config.Config.SQLALCHEMY_ENGINE_OPTIONS["pool_timeout"] == 30


def test_reader_and_writer_binds_receive_pool_options(monkeypatch, reload_config):
    monkeypatch.delenv("SQLALCHEMY_DISABLE_POOL", raising=False)
    monkeypatch.setenv("SQLALCHEMY_DATABASE_URI", "postgresql://writer/db")
    monkeypatch.setenv("SQLALCHEMY_DATABASE_READER_URI", "postgresql://reader/db")
    importlib.reload(config)

    for name, url in (("writer", "postgresql://writer/db"), ("reader", "postgresql://reader/db")):
        bind = config.Config.SQLALCHEMY_BINDS[name]
        assert bind["url"] == url
        assert bind["pool_recycle"] == 300


def test_disable_pool_gives_null_pool_to_default_reader_and_writer_engines(notify_api, monkeypatch, reload_config):
    # notify_api must be built first: blueprints only register on the first create_app() in a process.
    monkeypatch.setenv("SQLALCHEMY_DISABLE_POOL", "true")
    monkeypatch.setenv("SQLALCHEMY_DATABASE_URI", "postgresql://user:pass@writer-host/db")
    monkeypatch.setenv("SQLALCHEMY_DATABASE_READER_URI", "postgresql://user:pass@reader-host/db")
    importlib.reload(config)

    app = Flask("disable-pool-test")
    create_app(app, config=config.Test)

    with app.app_context():
        try:
            for bind in (None, "writer", "reader"):
                assert isinstance(db.engines[bind].pool, NullPool), bind
        finally:
            for engine in db.engines.values():
                engine.dispose()
