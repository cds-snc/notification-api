from flask import Flask

from app.dbsetup import RoutingSQLAlchemy


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
