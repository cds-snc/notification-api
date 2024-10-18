import os
import warnings
from contextlib import contextmanager

import pytest
import sqlalchemy
import xdist
from alembic.command import upgrade
from alembic.config import Config
from flask import Flask
from sqlalchemy.exc import SAWarning
from sqlalchemy.sql import delete, select
from sqlalchemy.sql import text as sa_text

from app import create_app, db, schemas

application = None


def pytest_sessionstart(session):
    """
    A pytest hook that runs before any test.
    Initialize a Flask application with the Flask-SQLAlchemy extension then creates the DB and prepares it for use.

    https://flask.palletsprojects.com/en/2.3.x/testing/
    https://flask-sqlalchemy.palletsprojects.com/en/3.0.x/quickstart/
    """
    global application

    app = Flask('test')
    application = create_app(app)

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
                if exc_class is not Exception
            }
            if error_handlers[None] == []:
                error_handlers.pop(None)

    create_test_db(application.config['SQLALCHEMY_DATABASE_URI'])

    BASE_DIR = os.path.dirname(os.path.dirname(__file__))
    ALEMBIC_CONFIG = os.path.join(BASE_DIR, 'migrations')
    config = Config(ALEMBIC_CONFIG + '/alembic.ini')
    config.set_main_option('script_location', ALEMBIC_CONFIG)

    with application.app_context():
        upgrade(config, 'head')
        database_prep()


@pytest.fixture(scope='session')
def notify_api():
    """
    yields application context
    """

    with application.app_context():
        yield application


@pytest.fixture(scope='function')
def client(notify_api):
    with notify_api.test_request_context(), notify_api.test_client() as client:
        yield client


def create_test_db(database_uri):
    db_uri_parts = database_uri.split('/')
    postgres_db_uri = '/'.join(db_uri_parts[:-1] + ['postgres'])

    postgres_db = sqlalchemy.create_engine(
        postgres_db_uri, echo=False, isolation_level='AUTOCOMMIT', client_encoding='utf8'
    )

    with postgres_db.connect() as conn:
        db_names = [name[0] for name in conn.execute(sa_text("""SELECT datname FROM pg_database;""")).all()]
        db_name = db_uri_parts[-1]
        if db_name not in db_names:
            print(f'\nmaking database: {db_name}')
            result = conn.execute(sa_text(f"""CREATE DATABASE {db_name};"""))
            result.close()

    postgres_db.dispose()


@pytest.fixture(scope='session')
def notify_db(notify_api):
    """
    Yield an instance of flask_sqlalchemy.SQLAlchemy.
        https://flask-sqlalchemy.palletsprojects.com/en/2.x/api/#flask_sqlalchemy.SQLAlchemy

    Use this fixture in other session-scoped fixtures.
    """

    yield db

    db.session.remove()
    db.engine.dispose()


@pytest.fixture
def notify_db_session(notify_db):
    """
    Use this fixture with other function-scoped fixtures.
    """

    yield notify_db
    notify_db.session.remove()
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


def database_prep():
    """
    This clears out all the residuals that built up over the years from the test DB.
    Only ran at the very start of the tests and is automatic due to autouse=True.
    """
    # Setup metadata with reflection so we can get tables from their string names
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', category=SAWarning)
        meta_data = db.MetaData(bind=db.engine)
        db.MetaData.reflect(meta_data)

    notify_service_id = application.config['NOTIFY_SERVICE_ID']
    notify_user_id = application.config['NOTIFY_USER_ID']

    # Used this format to refence the tables because model availability is inconsistent and it's best not to mix styles
    AB = meta_data.tables['annual_billing']
    db.session.execute(delete(AB).where(AB.c.service_id == notify_service_id))

    C = meta_data.tables['communication_items']
    db.session.execute(delete(C))

    SERT = meta_data.tables['service_email_reply_to']
    db.session.execute(delete(SERT).where(SERT.c.service_id == notify_service_id))

    SP = meta_data.tables['service_permissions']
    db.session.execute(delete(SP).where(SP.c.service_id == notify_service_id))

    SSS = meta_data.tables['service_sms_senders']
    db.session.execute(delete(SSS).where(SSS.c.service_id == notify_service_id))

    SH = meta_data.tables['services_history']
    db.session.execute(delete(SH).where(SH.c.id == notify_service_id))

    UtS = meta_data.tables['user_to_service']
    db.session.execute(delete(UtS).where(UtS.c.service_id == notify_service_id))

    TR = meta_data.tables['template_redacted']
    db.session.execute(delete(TR).where(TR.c.updated_by_id == notify_user_id))

    TH = meta_data.tables['templates_history']
    db.session.execute(delete(TH).where(TH.c.service_id == notify_service_id))

    T = meta_data.tables['templates']
    db.session.execute(delete(T).where(T.c.service_id == notify_service_id))

    S = meta_data.tables['services']
    db.session.execute(delete(S).where(S.c.id == notify_service_id))

    U = meta_data.tables['users']
    db.session.execute(delete(U).where(U.c.id == notify_user_id))

    R = meta_data.tables['rates']
    db.session.execute(delete(R))

    LR = meta_data.tables['letter_rates']
    db.session.execute(delete(LR))

    db.session.commit()


def pytest_sessionfinish(session, exitstatus):
    """
    A pytest hook that runs after all tests. Reports database is clear of extra entries after all tests have ran.
    Exit code is set to 1 if anything is left in any table.
    """
    # Guard to prevent this from running early
    if xdist.is_xdist_worker(session):
        return

    color = '\033[91m'
    reset = '\033[0m'
    TRUNCATE_ARTIFACTS = os.environ['TRUNCATE_ARTIFACTS'] == 'True'

    with application.app_context():
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', category=SAWarning)
            meta_data = db.MetaData(bind=db.engine)
            db.MetaData.reflect(meta_data)

        acceptable_counts = {
            'communication_items': 4,
            'job_status': 9,
            'key_types': 3,
            # 'provider_details': 9,  # TODO: 1631
            # 'provider_details_history': 9,  # TODO: 1631
            'provider_rates': 5,
            # 'rates': 2,
            'service_callback_channel': 2,
            'service_callback_type': 3,
            'service_permission_types': 12,
        }

        skip_tables = (
            'alembic_version',
            'auth_type',
            'branding_type',
            'dm_datetime',
            'key_types',
            'notification_status_types',
            'template_process_type',
            'provider_details',
            'provider_details_history',
        )
        to_be_deleted_tables = (
            'organisation_types',
            'invite_status_type',
            'job_status',
        )

        # Gather tablenames & sort
        table_list = sorted(
            [
                table
                for table in db.engine.table_names()
                if table not in skip_tables and table not in to_be_deleted_tables
            ]
        )

        tables_with_artifacts = []
        artifact_counts = []

        # Use metadata to query the table and add the table name to the list if there are any records
        for table_name in table_list:
            row_count = len(db.session.execute(select(meta_data.tables[table_name])).all())

            if table_name in acceptable_counts and row_count <= acceptable_counts[table_name]:
                continue
            elif row_count > 0:
                artifact_counts.append((row_count))
                tables_with_artifacts.append(table_name)
                session.exitstatus = 1

        if tables_with_artifacts and TRUNCATE_ARTIFACTS:
            print('\n')
            for i, table in enumerate(tables_with_artifacts):
                # Skip tables that may have necessary information
                if table not in acceptable_counts:
                    db.session.execute(sa_text(f"""TRUNCATE TABLE {table} CASCADE"""))
                    print(f'Truncating {color}{table}{reset} with cascade...{artifact_counts[i]} records removed')
                else:
                    print(f'Table {table} contains too many records but {color}cannot be truncated{reset}.')
            db.session.commit()
            print(
                f'\n\nThese tables contained artifacts: ' f'{tables_with_artifacts}\n\n{color}UNIT TESTS FAILED{reset}'
            )
        elif tables_with_artifacts:
            print(f'\n\nThese tables contain artifacts: ' f'{color}{tables_with_artifacts}\n\nUNIT TESTS FAILED{reset}')
        else:
            color = '\033[32m'  # Green - pulled out for clarity
            print(f'\n\n{color}DATABASE IS CLEAN{reset}')
