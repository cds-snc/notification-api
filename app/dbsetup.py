from functools import partial, cached_property

from flask_sqlalchemy import (BaseQuery, SignallingSession, SQLAlchemy, get_state)
from sqlalchemy import orm
from flask import _app_ctx_stack


class ExplicitRoutingSession(SignallingSession):
    """
    This session implementation will route to explicitly named bind.
    If no bind is mentioned with the session via the `using_bind` function,
    then the `reader` bind will get returned instead.
    """

    _name = None

    def get_bind(self, mapper=None, clause=None):
        # If reader and writer binds are not configured,
        # connect using the default SQLALCHEMY_DATABASE_URI
        if not self.binds_setup:
            return super().get_bind(mapper, clause)

        return self.load_balance(mapper, clause)

    def load_balance(self, mapper=None, clause=None):
        # Use the explicit name if present
        if self._name and not self._flushing:
            bind = self._name
            self._name = None
            self.app.logger.debug(f"Connecting -> {bind}")
            return get_state(self.app).db.get_engine(self.app, bind=bind)

        # Everything else goes to the writer engine
        else:
            self.app.logger.debug("Connecting -> writer")
            return get_state(self.app).db.get_engine(self.app, bind='writer')

    def using_bind(self, name):
        self._name = name
        return self

    @cached_property
    def binds_setup(self):
        binds = self.app.config['SQLALCHEMY_BINDS'] or {}
        return all([k in binds for k in ['reader', 'writer']])


class RoutingSQLAlchemy(SQLAlchemy):
    def on_reader(self):
        return self.session().using_bind('reader')

    def apply_driver_hacks(self, app, info, options):
        super().apply_driver_hacks(app, info, options)
        if 'connect_args' not in options:
            options['connect_args'] = {}
        options['connect_args']["options"] = "-c statement_timeout={}".format(
            int(app.config['SQLALCHEMY_STATEMENT_TIMEOUT']) * 1000
        )

    def create_scoped_session(self, options=None):
        options = options or {}
        scopefunc = options.pop('scopefunc', _app_ctx_stack.__ident_func__)
        options.setdefault('query_cls', BaseQuery)

        return orm.scoped_session(
            partial(ExplicitRoutingSession, self, **options),
            scopefunc=scopefunc
        )
