from functools import cached_property, partial
from typing import Optional
import greenlet

from flask import _app_ctx_stack  # type: ignore
from flask_sqlalchemy import BaseQuery, SignallingSession, SQLAlchemy, get_state
from sqlalchemy import orm

class ExplicitRoutingSession(SignallingSession):
    """
    This session implementation will route to explicitly named bind.
    If no bind is mentioned with the session via the `using_bind` function,
    then the `reader` bind will get returned instead.
    """

    _name: Optional[str] = None

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
            return get_state(self.app).db.get_engine(self.app, bind="writer")

    def using_bind(self, name: str):
        self._name = name
        return self

    @cached_property
    def binds_setup(self):
        binds = self.app.config["SQLALCHEMY_BINDS"] or {}
        return all([k in binds for k in ["reader", "writer"]])


class RoutingSQLAlchemy(SQLAlchemy):
    def on_reader(self):
        return self.session().using_bind("reader")

    def create_scoped_session(self, options=None):
        options = options or {}
        options.setdefault("query_cls", BaseQuery)

        return orm.scoped_session(partial(ExplicitRoutingSession, self, **options), scopefunc=greenlet.getcurrent)
