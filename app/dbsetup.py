from functools import cached_property, partial
from time import perf_counter
from typing import Any, Optional

import greenlet  # type: ignore
import sqlalchemy.types as types
from flask import Flask
from flask_sqlalchemy import BaseQuery, SignallingSession, SQLAlchemy, get_state
from sqlalchemy import event, orm


# adapted from https://r2c.dev/blog/2020/fixing-leaky-logs-how-to-find-a-bug-and-ensure-it-never-returns/
class SensitiveString(types.TypeDecorator):
    """
    String column type for use with SQLAlchemy models whose
    content should not appear in logs or exceptions
    """

    impl = types.String

    class Repr(str):
        def __repr__(self) -> str:
            return "********"

    def process_bind_param(self, value: Optional[str], dialect: Any) -> Optional[Repr]:
        return self.Repr(value) if value else None

    def process_result_value(self, value: Optional[Repr], dialect: Any) -> Optional[str]:
        return str(value) if value else None


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
    SensitiveString = SensitiveString

    def on_reader(self):
        return self.session().using_bind("reader")

    def create_scoped_session(self, options=None):
        options = options or {}
        options.setdefault("query_cls", BaseQuery)

        return orm.scoped_session(partial(ExplicitRoutingSession, self, **options), scopefunc=greenlet.getcurrent)


def enable_sqlalchemy_debug_logging(app: Flask, db: RoutingSQLAlchemy) -> None:
    if not app.config.get("SQLALCHEMY_DEBUG_POOL_LOGGING", False):
        return

    binds = app.config.get("SQLALCHEMY_BINDS") or {}
    bind_names = list(binds.keys()) if binds else [None]

    for bind in bind_names:
        engine = db.get_engine(app, bind=bind)

        if getattr(engine, "_notify_debug_events_attached", False):
            continue

        setattr(engine, "_notify_debug_events_attached", True)
        bind_name = bind or "default"
        slow_query_threshold_ms = int(app.config.get("SQLALCHEMY_DEBUG_QUERY_MS", 250))

        @event.listens_for(engine, "do_connect", retval=True)
        def on_do_connect(dialect, conn_rec, cargs, cparams, _bind_name=bind_name, _engine=engine):
            start = perf_counter()
            try:
                return dialect.connect(*cargs, **cparams)
            finally:
                elapsed_ms = (perf_counter() - start) * 1000
                app.logger.info(f"sqlalchemy.connect bind={_bind_name} elapsed_ms={elapsed_ms:.2f} pool={_engine.pool.status()}")

        @event.listens_for(engine, "checkout")
        def on_checkout(_dbapi_conn, conn_rec, _conn_proxy, _bind_name=bind_name, _engine=engine):
            conn_rec.info["notify_checked_out_at"] = perf_counter()
            app.logger.info(f"sqlalchemy.checkout bind={_bind_name} pool={_engine.pool.status()}")

        @event.listens_for(engine, "checkin")
        def on_checkin(_dbapi_conn, conn_rec, _bind_name=bind_name, _engine=engine):
            started = conn_rec.info.pop("notify_checked_out_at", None)
            held_ms = (perf_counter() - started) * 1000 if started else None
            held_suffix = f" held_ms={held_ms:.2f}" if held_ms is not None else ""
            app.logger.info(f"sqlalchemy.checkin bind={_bind_name}{held_suffix} pool={_engine.pool.status()}")

        @event.listens_for(engine, "before_cursor_execute")
        def before_cursor_execute(conn, _cursor, _statement, _parameters, _context, _executemany):
            conn.info.setdefault("notify_query_start", []).append(perf_counter())

        @event.listens_for(engine, "after_cursor_execute")
        def after_cursor_execute(
            conn,
            _cursor,
            statement,
            _parameters,
            _context,
            _executemany,
            _bind_name=bind_name,
            _threshold_ms=slow_query_threshold_ms,
        ):
            starts = conn.info.get("notify_query_start", [])
            started = starts.pop() if starts else None
            if started is None:
                return
            elapsed_ms = (perf_counter() - started) * 1000
            if elapsed_ms >= _threshold_ms:
                compact_statement = " ".join(statement.split())
                if len(compact_statement) > 240:
                    compact_statement = f"{compact_statement[:240]}..."
                app.logger.info(
                    f"sqlalchemy.query bind={_bind_name} elapsed_ms={elapsed_ms:.2f} threshold_ms={_threshold_ms} statement={compact_statement}"
                )
