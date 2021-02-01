from abc import abstractmethod
from functools import lru_cache, partial

from flask_sqlalchemy import (BaseQuery, SignallingSession, SQLAlchemy, get_state)
from sqlalchemy import orm
from flask import _app_ctx_stack


class RoutingSession(SignallingSession):
    def get_bind(self, mapper=None, clause=None):
        # If there are no binds configured, connect using the default
        # SQLALCHEMY_DATABASE_URI
        binds = self.app.config['SQLALCHEMY_BINDS'] or {}
        binds_setup = all([k in binds for k in ['reader', 'writer']])
        if not binds_setup:
            super().get_bind(mapper, clause)

        return self.load_balance(mapper, clause)

    @abstractmethod
    def load_balance(self, mapper=None, clause=None):
        pass


class ExplicitRoutingSession(RoutingSession):
    """This session implementation will route to explicitly named bind.
    If no bind is mentioned with the session via the `using_bind` function,
    then the `reader` bind will get returned instead.
    """

    _name = None

    def load_balance(self, mapper=None, clause=None):
        # Use the explicit name if present
        if self._name:
            bind = self._name
            self._name = None
            print(f"Connecting -> {bind}")
            return get_state(self.app).db.get_engine(self.app, bind=bind)

        # Everything else goes to the writer engine
        else:
            print("Connecting -> WRITER")
            return get_state(self.app).db.get_engine(self.app, bind='writer')

    def using_bind(self, name):
        self._name = name
        return self


class ImplicitRoutingSession(RoutingSession):
    """
    This session implementation will route to implicit bind via automatic
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
    DATA_MODIFICATION_LITERALS = set([
        'update',
        'delete',
        'create',
        'copy',
        'insert',
        'drop',
        'alter'
    ])

    def load_balance(self, state, mapper=None, clause=None):
        # Writes go to the writer instance
        if self._flushing or clause is None or not self._is_clean():
            print("Connecting -> WRITER")
            return state.db.get_engine(self.app, bind='writer')

        # We might deal with an undetected writes so let's check the clause itself
        elif clause is not None and self._is_query_modify(clause.compile()):
            print(f"Connecting -> WRITER {clause.compile()}")
            return state.db.get_engine(self.app, bind='writer')

        # Everything else goes to the reader instance(s)
        else:
            print(f"Connecting -> READER {clause.compile()}")
            return state.db.get_engine(self.app, bind='reader')

    @lru_cache(maxsize=1000)
    def _is_query_modify(self, query) -> bool:
        return any(
            [literal.lower() in self.DATA_MODIFICATION_LITERALS for literal in str(query).split(' ')]
        )


class RoutingSQLAlchemy(SQLAlchemy):
    def apply_driver_hacks(self, app, info, options):
        super().apply_driver_hacks(app, info, options)
        if 'connect_args' not in options:
            options['connect_args'] = {}
        options['connect_args']["options"] = "-c statement_timeout={}".format(
            int(app.config['SQLALCHEMY_STATEMENT_TIMEOUT']) * 1000
        )
        self.session.using_bind = lambda s: self.session().using_bind(s)

    def create_scoped_session(self, options=None):
        if options is None:
            options = {}
        scopefunc = options.pop('scopefunc', _app_ctx_stack.__ident_func__)
        options.setdefault('query_cls', BaseQuery)
        return orm.scoped_session(
            partial(ExplicitRoutingSession, self, **options), scopefunc=scopefunc
        )
