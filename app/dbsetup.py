from abc import abstractmethod
from flask_sqlalchemy import BaseQuery, SignallingSession, SQLAlchemy, get_state
from flask_sqlalchemy.model import Model
from sqlalchemy import orm
from functools import partial
from flask import current_app


class RoutingSession(SignallingSession):

    _name = None

    def __init__(self, db, autocommit=False, autoflush=True, **options):
        self.app = db.get_app()
        self.db = db
        self._model_changes = {}
        options.setdefault("query_cls", BaseQuery)
        orm.Session.__init__(
            self, autocommit=autocommit, autoflush=autoflush,
            bind=db.engine,
            binds=db.get_binds(self.app), **options)

    def get_bind(self, mapper=None, clause=None):
        try:
            state = get_state(self.app)
        except (AssertionError, AttributeError, TypeError) as err:
            current_app.logger.error(
                "cant get configuration. default bind. Error:" + err)
            return orm.Session.get_bind(self, mapper, clause)

        """
        If there are no binds configured, connect using the default
        SQLALCHEMY_DATABASE_URI
        """
        if state is None or not self.app.config['SQLALCHEMY_BINDS']:
            if not self.app.debug:
                current_app.logger.debug("Connecting -> DEFAULT")
            return orm.Session.get_bind(self, mapper, clause)

        return self.load_balance(state, mapper, clause)

    @abstractmethod
    def load_balance(self, state, mapper=None, clause=None):
        pass

    @abstractmethod
    def using_bind(self, name):
        pass


class ImplicitRoutingSession(RoutingSession):
    """This session implementation will route to implicit bind via automatic
    detection.

    If no bind is explicitly mentioned with the session via the `using_bind`
    function, then the logic tries to determine if the current session will
    lead to a modification in the database state. This automation logic work
    as follows:

    First, we look if the `flushing` property is enabled in the session. If
    that is true, it indicates that some state need to be flushed to the
    database. The writer bind gets returned.

    Second, we look at the generate query if the SQL statement is attached
    to the current session. Such statement is usually attached when using
    SQLAlchemy DSL syntax for queries. If that SQL statement contains
    certain keywords such as `update` or `delete`, then the writer bind
    gets returned.

    Third, failing previous detection of intended changes in the database,
    the reader bind gets returned.

    If this automatic detection does not work, then it is advised to
    specify the bind manually via `using_bind` available with this Session
    implementation.
    """

    DATA_MODIFICATION_LITERALS = [
        'update',
        'delete',
        'create',
        'copy',
        'insert',
        'drop',
        'alter'
    ]

    def __init__(self, db, autocommit=False, autoflush=False, **options):
        RoutingSession.__init__(
            self, db, autocommit=autocommit, autoflush=autoflush, **options)

    def load_balance(self, state, mapper=None, clause=None):
        # Use the explicit bind if present
        if self._name:
            self.app.logger.debug("Connecting -> {}".format(self._name))
            return state.db.get_engine(self.app, bind=self._name)

        # Writes go to the writer instance
        elif self._flushing:
            current_app.logger.debug("Connecting -> WRITER")
            return state.db.get_engine(self.app, bind='writer')

        # We might deal with an undetected writes so let's check the clause itself
        elif clause is not None and self._is_query_modify(clause.compile()):
            current_app.logger.debug("Connecting -> WRITER")
            return state.db.get_engine(self.app, bind='writer')

        # Everything else goes to the reader instance(s)
        else:
            current_app.logger.debug("Connecting -> READER")
            return state.db.get_engine(self.app, bind='reader')

    def _is_query_modify(self, query) -> bool:
        query_literals = [literal.lower() for literal in str(query).split(' ')]
        intersection = [
            literal for literal in query_literals
            if literal in self.DATA_MODIFICATION_LITERALS
        ]
        return len(intersection) > 0

    def using_bind(self, name):
        s = ImplicitRoutingSession(self.db)
        vars(s).update(vars(self))
        s._name = name
        return s


class ExplicitRoutingSession(RoutingSession):
    """This session implementation will route to explicitly named bind.

    If no bind is mentioned with the session via the `using_bind` function,
    then the `reader` bind will get returned instead.
    """

    def __init__(self, db, autocommit=False, autoflush=True, **options):
        RoutingSession.__init__(
            self, db, autocommit=autocommit, autoflush=autoflush, **options)

    def load_balance(self, state, mapper=None, clause=None):
        # Use the explicit name if present
        if self._name:
            self.app.logger.debug("Connecting -> {}".format(self._name))
            return state.db.get_engine(self.app, bind=self._name)

        # Everything else goes to the writer engine
        else:
            current_app.logger.debug("Connecting -> WRITER")
            return state.db.get_engine(self.app, bind='writer')

    def using_bind(self, name):
        s = ExplicitRoutingSession(self.db)
        vars(s).update(vars(self))
        s._name = name
        return s


class NotifySQLAlchemy(SQLAlchemy):
    """We need to subclass SQLAlchemy in order to override create_engine options"""

    def apply_driver_hacks(self, app, info, options):
        super().apply_driver_hacks(app, info, options)
        if 'connect_args' not in options:
            options['connect_args'] = {}
        options['connect_args']["options"] = "-c statement_timeout={}".format(
            int(app.config['SQLALCHEMY_STATEMENT_TIMEOUT']) * 1000
        )


class RoutingSQLAlchemy(NotifySQLAlchemy):
    """We need to subclass SQLAlchemy in order to override create_engine options"""

    def __init__(self, *args, **kwargs):
        SQLAlchemy.__init__(self, use_native_unicode=True, session_options=None,
                            query_class=BaseQuery, model_class=Model,
                            *args, **kwargs)
        self.session.using_bind = lambda s: self.session().using_bind(s)

    def create_scoped_session(self, options=None):
        if options is None:
            options = {}
        scopefunc = options.pop('scopefunc', None)
        return orm.scoped_session(
            partial(ExplicitRoutingSession, self, **options), scopefunc=scopefunc
        )
