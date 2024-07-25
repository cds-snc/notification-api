from flask import url_for

import pytest


@pytest.mark.parametrize(
    'query_string',
    [
        ({'foo': 'bar'}, 'foo=bar'),
        ({}, ''),
        ({'foo': 'bar', 'baz': 'qux'}, 'foo=bar&baz=qux'),
    ],
)
def test_ut_get_internal(client, mocker, query_string):
    mock_logger = mocker.patch('app.internal.rest.current_app.logger.info')
    response = client.get(url_for('internal.handler', generic='foo', **query_string[0]))
    assert response.status_code == 200
    assert response.text == f'GET request received for endpoint /internal/foo?{query_string[1]}'

    actual = mock_logger.call_args_list[0].args[0]
    expected = 'Generic Internal Request: %s'
    assert actual == expected, 'The logger was not called with the expected message.'

    actual = mock_logger.call_args_list[0].args[1]
    assert f"QUERY_STRING: b'{query_string[1]}'" in actual, 'The logged info did not contain the correct QUERY_STRING.'


@pytest.mark.parametrize('method', ['GET', 'POST'])
def test_ut_internal_logging(client, mocker, method):
    mock_logger = mocker.patch('app.internal.rest.current_app.logger.info')
    mock_request = mocker.patch('app.internal.rest.request')
    mock_request.method = method
    mock_request.root_path = 'root'
    mock_request.path = '/internal/foo'
    mock_request.query_string = b'foo=bar'
    mock_request.url_rule = '/internal/<generic>'
    mock_request.trace_id = '123'
    mock_request.headers = {'key': 'value', 'key2': 'value2'}
    if method == 'POST':
        mock_request.json = {'key': 'value'}
    client.get(url_for('internal.handler', generic='foo'))
    actual = mock_logger.call_args_list[0].args[0]
    expected = 'Generic Internal Request: %s'
    assert actual == expected, 'The logger was not called with the expected message.'

    actual = mock_logger.call_args_list[0].args[1]
    assert f'METHOD: {method}' in actual, 'The logged info did not contain the correct METHOD.'
    assert 'ROOT_PATH: root' in actual, 'The logged info did not contain the correct ROOT_PATH.'
    assert 'PATH: /internal/foo' in actual, 'The logged info did not contain the correct PATH.'
    assert 'URL_RULE: /internal/<generic>' in actual, 'The logged info did not contain the correct URL_RULE.'
    assert 'TRACE_ID: 123' in actual, 'The logged info did not contain the correct TRACE_ID.'
    assert 'HEADERS: ' in actual, 'The logged info did not contain the correct HEADERS.'
    assert "QUERY_STRING: b'foo=bar'" in actual, 'The logged info did not contain the correct QUERY_STRING.'
    if method == 'POST':
        assert "JSON: {'key': 'value'}" in actual, 'The logged info did not contain the correct JSON.'


@pytest.mark.parametrize(
    'query_string',
    [
        ({'foo': 'bar'}, b'foo=bar'),
        ({}, b''),
        ({'foo': 'bar', 'baz': 'qux'}, b'foo=bar&baz=qux'),
    ],
)
def test_ut_post_internal(client, mocker, query_string):
    mock_logger = mocker.patch('app.internal.rest.current_app.logger.info')
    response = client.post(url_for('internal.handler', generic='bar', **query_string[0]), json={'key': 'value'})
    assert response.status_code == 200
    assert response.json == {'bar': {'key': 'value'}}

    actual = mock_logger.call_args_list[0].args[0]
    expected = 'Generic Internal Request: %s'
    assert actual == expected, 'The logger was not called with the expected message.'

    actual = mock_logger.call_args_list[0].args[1]
    assert f'QUERY_STRING: {query_string[1]}' in actual, 'The logged info did not contain the correct QUERY_STRING.'
