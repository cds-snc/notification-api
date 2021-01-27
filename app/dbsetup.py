from flask_sqlalchemy import SQLAlchemy as _SQLAlchemy, get_state
from sqlalchemy import orm
from functools import partial
from flask import current_app
from flask_sqlalchemy import SQLAlchemy as _SQLAlchemy, get_state


class RoutingSession(orm.Session):

    _name = None

    def __init__(self, db, autocommit=False, autoflush=False, **options):
        self.app = db.get_app()
        self.db = db
        self._model_changes = {}
        orm.Session.__init__(
            self, autocommit=autocommit, autoflush=autoflush,
            bind=db.engine,
            binds=db.get_binds(self.app), **options)

    def get_bind(self, mapper=None, clause=None):
        try:
            state = get_state(self.app)
        except (AssertionError, AttributeError, TypeError) as err:
            # TODO: Change the log to DEBUG level.
            current_app.logger.info(
                "cant get configuration. default bind. Error:" + err)
            return orm.Session.get_bind(self, mapper, clause)

        """
        If there are no binds configured, connect using the default
        SQLALCHEMY_DATABASE_URI
        """
        if state is None or not self.app.config['SQLALCHEMY_BINDS']:
            if not self.app.debug:
                # TODO: Change the log to DEBUG level.
                current_app.logger.info("Connecting -> DEFAULT")
            return orm.Session.get_bind(self, mapper, clause)

        elif self._name:
            # TODO: Change the log to DEBUG level.
            self.app.logger.debug("Connecting -> {}".format(self._name))
            return state.db.get_engine(self.app, bind=self._name)

        # Writes go to the writer instance
        elif self._flushing:  # we who are about to write, salute you
            # TODO: Change the log to DEBUG level.
            current_app.logger.info("Connecting -> WRITER")
            return state.db.get_engine(self.app, bind='writer')

        # Everything else goes to the reader instance(s)
        else:
            current_app.logger.info("Connecting -> READER")
            return state.db.get_engine(self.app, bind='reader')

    def using_bind(self, name):
        s = RoutingSession(self.db)
        vars(s).update(vars(self))
        s._name = name
        return s


class RoutingSQLAlchemy(_SQLAlchemy):
    """We need to subclass SQLAlchemy in order to override create_engine options"""

    def __init__(self, *args, **kwargs):
        _SQLAlchemy.__init__(self, *args, **kwargs)
        self.session.using_bind = lambda s: self.session().using_bind(s)

    def apply_driver_hacks(self, app, info, options):
        super().apply_driver_hacks(app, info, options)
        if 'connect_args' not in options:
            options['connect_args'] = {}
        options['connect_args']["options"] = "-c statement_timeout={}".format(
            int(app.config['SQLALCHEMY_STATEMENT_TIMEOUT']) * 1000
        )

    def create_scoped_session(self, options=None):
        if options is None:
            options = {}
        scopefunc = options.pop('scopefunc', None)
        return orm.scoped_session(
            partial(RoutingSession, self, **options), scopefunc=scopefunc
        )
