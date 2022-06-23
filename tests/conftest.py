import pytest
import sqlalchemy
import os
from alembic.command import upgrade
from alembic.config import Config
from app import create_app, db, schemas
from contextlib import contextmanager
from flask import Flask


@pytest.fixture(scope='session')
def notify_api():
    app = Flask('test')
    create_app(app)

    # deattach server-error error handlers - error_handler_spec looks like:
    #   {'blueprint_name': {
    #       status_code: [error_handlers],
    #       None: { ExceptionClass: error_handler }
    # }}
    for error_handlers in app.error_handler_spec.values():
        error_handlers.pop(500, None)
        if None in error_handlers:
            error_handlers[None] = {
                exc_class: error_handler
                for exc_class, error_handler in error_handlers[None].items()
                if exc_class != Exception
            }
            if error_handlers[None] == []:
                error_handlers.pop(None)

    ctx = app.app_context()
    ctx.push()

    yield app

    ctx.pop()


@pytest.fixture(scope='function')
def client(notify_api):
    with notify_api.test_request_context(), notify_api.test_client() as client:
        yield client


def create_test_db(database_uri):
    db_uri_parts = database_uri.split('/')
    postgres_db_uri = '/'.join(db_uri_parts[:-1] + ['postgres'])

    postgres_db = sqlalchemy.create_engine(
        postgres_db_uri,
        echo=False,
        isolation_level='AUTOCOMMIT',
        client_encoding='utf8'
    )

    try:
        result = postgres_db.execute(sqlalchemy.sql.text('CREATE DATABASE {}'.format(db_uri_parts[-1])))
        result.close()
    except sqlalchemy.exc.ProgrammingError:
        # The database "test_notification_api_master" already exists.
        pass
    finally:
        postgres_db.dispose()


@pytest.fixture(scope='session')
def notify_db(notify_api, worker_id):
    """
    Yield an instance of flask_sqlalchemy.SQLAlchemy.
        https://flask-sqlalchemy.palletsprojects.com/en/2.x/api/#flask_sqlalchemy.SQLAlchemy
    """

    assert "test_notification_api" in db.engine.url.database, "Don't run tests against main db."

    # Create a database for this worker thread.
    from flask import current_app
    current_app.config['SQLALCHEMY_DATABASE_URI'] += f"_{worker_id}"
    create_test_db(current_app.config['SQLALCHEMY_DATABASE_URI'])

    BASE_DIR = os.path.dirname(os.path.dirname(__file__))
    ALEMBIC_CONFIG = os.path.join(BASE_DIR, 'migrations')
    config = Config(ALEMBIC_CONFIG + '/alembic.ini')
    config.set_main_option("script_location", ALEMBIC_CONFIG)

    with notify_api.app_context():
        upgrade(config, 'head')

    yield db

    db.session.remove()
    db.get_engine(notify_api).dispose()

#     TODO: properly delete the database after all workers finish?


@pytest.fixture(scope='function')
def notify_db_session(notify_db):
    yield notify_db

    notify_db.session.remove()
    for tbl in reversed(notify_db.metadata.sorted_tables):
        if tbl.name not in ["provider_details",
                            "key_types",
                            "branding_type",
                            "job_status",
                            "provider_details_history",
                            "template_process_type",
                            "notification_status_types",
                            "organisation_types",
                            "service_permission_types",
                            "auth_type",
                            "invite_status_type",
                            "service_callback_type",
                            "service_callback_channel"]:
            notify_db.engine.execute(tbl.delete())
    notify_db.session.commit()


@pytest.fixture
def os_environ():
    """
    Copy os.environ, and restore it after the test runs.  Use this
    whenever you expect code to edit environment variables.
    """

    old_env = os.environ.copy()
    yield
    os.environ = old_env


def pytest_generate_tests(metafunc):
    # Copied from https://gist.github.com/pfctdayelise/5719730
    idparametrize = metafunc.definition.get_closest_marker('idparametrize')
    if idparametrize:
        argnames, testdata = idparametrize.args
        ids, argvalues = zip(*sorted(testdata.items()))
        metafunc.parametrize(argnames, argvalues, ids=ids)


# this is necessary for using https://github.com/jeancochrane/pytest-flask-sqlalchemy
@pytest.fixture(scope='session')
def _db(notify_db):
    return notify_db


@contextmanager
def set_config(app, name, value):
    old_val = app.config.get(name)
    app.config[name] = value
    try:
        yield
    finally:
        app.config[name] = old_val


@contextmanager
def set_config_values(app: object, dict: object) -> object:
    old_values = {}

    for key in dict:
        old_values[key] = app.config.get(key)
        app.config[key] = dict[key]

    try:
        yield
    finally:
        for key in dict:
            app.config[key] = old_values[key]


class Matcher:
    def __init__(self, description, key):
        self.description = description
        self.key = key

    def __eq__(self, other):
        return self.key(other)

    def __repr__(self):
        return '<Matcher: {}>'.format(self.description)


schemas.service_schema = schemas.ServiceSchema(session=db.session)
schemas.template_schema = schemas.TemplateSchema(session=db.session)
schemas.api_key_schema = schemas.ApiKeySchema(session=db.session)
schemas.job_schema = schemas.JobSchema(session=db.session)
schemas.invited_user_schema = schemas.InvitedUserSchema(session=db.session)
