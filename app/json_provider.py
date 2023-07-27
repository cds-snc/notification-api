import json

from flask.json.provider import JSONProvider, _default
from sqlalchemy.engine.row import Row


def default_encoder(o):
    # Support for sqlalchemy.engine.row.Row
    if isinstance(o, Row):
        row: Row = o
        m: dict = row._asdict()
        return m
    # Redirect to default
    return _default(o)


class NotifyJSONProvider(JSONProvider):
    """A JSON provider that adds edge case support for the Notify Python stack.

    Namely, these are currently supported:

    1. Added support for the sqlalchemy.engine.row.Row data type. When we
       upgraded to version 4, a few JSON serialization started to fail as
       the library now returns a Row object on the session.query returns.
       This encoder adds support to convert it to a dict, which the json
       package supports by default.

    see https://github.com/pallets/flask/pull/4692 for details on JSONProvider
    """

    def dumps(self, obj, *, option=None, **kwargs):
        return json.dumps(obj, default=default_encoder, **kwargs)

    def loads(self, s, **kwargs):
        return json.loads(s, **kwargs)

    def response(self, *args, **kwargs):
        obj = self._prepare_response_obj(args, kwargs)
        dumped = self.dumps(obj)
        return self._app.response_class(dumped, mimetype="application/json")
