import pytest
from flask import Flask

from app import create_app, db
from app.config import Test
from app.dbsetup import RoutingSQLAlchemy, enable_sqlalchemy_debug_logging

WRITER_URI = "postgresql://user:pass@writer-host/notification_api"
READER_URI = "postgresql://user:pass@reader-host/notification_api"
ENGINE_OPTIONS = {"pool_size": 7, "pool_timeout": 12, "pool_recycle": 300}


def _create_app_with_binds(binds):
    config = type(
        "BindsTestConfig",
        (Test,),
        {
            "SQLALCHEMY_DATABASE_URI": WRITER_URI,
            "SQLALCHEMY_DATABASE_READER_URI": READER_URI,
            "SQLALCHEMY_BINDS": binds,
        },
    )
    app = Flask("binds-test")
    create_app(app, config=config)
    return app, config


def test_create_app_rewrites_dict_bind_urls_and_preserves_engine_options(notify_api):
    # notify_api must be built first: blueprints only register on the first create_app() in a process.
    binds = {
        "writer": {"url": WRITER_URI, **ENGINE_OPTIONS},
        "reader": {"url": READER_URI, **ENGINE_OPTIONS},
    }
    app, config = _create_app_with_binds(binds)

    for name, uri in (("writer", WRITER_URI), ("reader", READER_URI)):
        bind = app.config["SQLALCHEMY_BINDS"][name]
        assert bind["url"] == uri.replace("postgresql://", "postgresql+psycopg2://", 1)
        assert {key: bind[key] for key in ENGINE_OPTIONS} == ENGINE_OPTIONS
        # The config class's dicts must not be rewritten in place.
        assert config.SQLALCHEMY_BINDS[name]["url"] == uri

    with app.app_context():
        try:
            for name in ("writer", "reader"):
                engine = db.engines[name]
                assert engine.url.drivername == "postgresql+psycopg2"
                assert engine.pool.size() == 7
                assert engine.pool._timeout == 12
                assert engine.pool._recycle == 300
        finally:
            for engine in db.engines.values():
                engine.dispose()


def test_create_app_rewrites_string_bind_urls(notify_api):
    app, _ = _create_app_with_binds({"writer": WRITER_URI, "reader": READER_URI})

    assert app.config["SQLALCHEMY_BINDS"] == {
        "writer": WRITER_URI.replace("postgresql://", "postgresql+psycopg2://", 1),
        "reader": READER_URI.replace("postgresql://", "postgresql+psycopg2://", 1),
    }

    with app.app_context():
        for engine in db.engines.values():
            engine.dispose()


@pytest.mark.parametrize("bind", ["writer", "reader"])
def test_live_engines_recycle_connections(notify_api, bind):
    with notify_api.app_context():
        pool = db.engines[bind].pool

        assert pool._recycle == 300


def test_routing_session_uses_explicit_reader_then_writer():
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite://"
    app.config["SQLALCHEMY_BINDS"] = {"reader": "sqlite://", "writer": "sqlite://"}

    db = RoutingSQLAlchemy()
    db.init_app(app)

    with app.app_context():
        session = db.session()

        assert session.get_bind() is db.engines["writer"]
        assert session.using_bind("reader").get_bind() is db.engines["reader"]
        assert session.get_bind() is db.engines["writer"]

        db.session.remove()


def test_debug_logging_resolves_engines_without_an_app_context():
    app = Flask(__name__)
    app.config.update(
        SQLALCHEMY_DATABASE_URI="sqlite://",
        SQLALCHEMY_DEBUG_POOL_LOGGING=True,
    )

    db = RoutingSQLAlchemy()
    db.init_app(app)

    enable_sqlalchemy_debug_logging(app, db)

    with app.app_context():
        assert db.engines[None]._notify_debug_events_attached is True
