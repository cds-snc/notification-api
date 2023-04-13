from app.clients.salesforce.salesforce_utils import (
    get_name_parts,
    parse_result,
    query_one,
    query_param_sanitize,
)


def test_get_name_parts():
    assert get_name_parts("Frodo Baggins") == {"first": "Frodo", "last": "Baggins"}
    assert get_name_parts("Smaug") == {"first": "", "last": "Smaug"}
    assert get_name_parts("") == {"first": "", "last": ""}
    assert get_name_parts("Gandalf The Grey") == {"first": "Gandalf", "last": "The Grey"}


def test_query_one_result(mocker):
    mock_session = mocker.MagicMock()
    mock_session.query.return_value = {"totalSize": 1, "records": [{"id": "123"}]}
    assert query_one(mock_session, "some query") == {"id": "123"}
    mock_session.query.assert_called_once_with("some query")


def test_query_one_no_results(mocker, notify_api):
    mock_session = mocker.MagicMock()
    with notify_api.app_context():
        mock_session.query.side_effect = [{"totalSize": 2}, {}]
        assert query_one(mock_session, "some query") is None
        assert query_one(mock_session, "some query") is None


def test_query_param_sanitize():
    assert query_param_sanitize("some string") == "some string"
    assert query_param_sanitize("fancy'ish apostrophe's") == "fancy\\'ish apostrophe\\'s"


def test_parse_result(notify_api):
    with notify_api.app_context():
        assert parse_result(200, "int") is True
        assert parse_result(299, "int") is True
        assert parse_result(100, "int") is False
        assert parse_result(400, "int") is False
        assert parse_result(500, "int") is False
        assert parse_result({"success": True}, "dict") is True
        assert parse_result({"success": False}, "dict") is False
        assert parse_result({}, "dict") is False
