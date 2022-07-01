# from sqlalchemy.ext.declarative import DeclarativeMeta
from flask.json import JSONEncoder
from sqlalchemy.engine.row import Row


class NotifyJSONEncoder(JSONEncoder):
    """A JSON encoder that adds edge case support for the Notify Python stack.

    Namely, these are currently supported:

    1. Added support for the sqlalchemy.engine.row.Row data type. When we
       upgraded to version 4, a few JSON serialization started to fail as
       the library now returns a Row object on the session.query returns.
       This encoder adds support to convert it to a dict, which the json
       package supports by default.
    """

    def default(self, o):
        # Support for sqlalchemy.engine.row.Row
        if isinstance(o, Row):
            row: Row = o
            m: dict = row._asdict()
            return m
        # Redirect to default JSON encoder support.
        return JSONEncoder.default(self, o)
