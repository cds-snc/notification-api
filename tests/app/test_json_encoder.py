import json

import pytest
from sqlalchemy.engine.row import Row

from app.json_encoder import NotifyJSONEncoder


class TestNotifyJSONEncoder:
    @pytest.fixture()
    def row(self, mocker):
        row = mocker.patch("sqlalchemy.engine.row.Row", spec=Row)
        row._asdict.return_value = {"key1": "value1", "key2": "value2"}
        return row

    def test_serialization_row(self, notify_api, row):
        serialized: str = json.dumps(row, cls=NotifyJSONEncoder)
        assert '{"key1": "value1", "key2": "value2"}' in serialized
