import pytest
from sqlalchemy.engine.row import Row

from app.json_provider import NotifyJSONProvider


class TestNotifyJSONProvider:
    @pytest.fixture()
    def row(self, mocker):
        row = mocker.patch("sqlalchemy.engine.row.Row", spec=Row)
        row._asdict.return_value = {"key1": "value1", "key2": "value2"}
        return row

    def test_serialization_row(self, notify_api, row):
        jp = NotifyJSONProvider(notify_api)
        serialized: str = jp.dumps(row)
        assert '{"key1": "value1", "key2": "value2"}' in serialized
