from flask import Flask

from app.dbsetup import RoutingSQLAlchemy, enable_sqlalchemy_debug_logging


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
