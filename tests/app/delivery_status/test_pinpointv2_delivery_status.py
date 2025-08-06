from flask import url_for
import pytest


@pytest.mark.parametrize(
    'post_json',
    [
        {},
        {'foo': 'bar'},
        {'foo': 'bar', 'baz': 'qux'},
    ],
)
def test_post_delivery_status(client, mocker, post_json):
    mock_logger = mocker.patch('app.delivery_status.rest.current_app.logger.info')

    response = client.post(
        url_for('pinpoint_v2.handler'),
        json=post_json,
        headers=[('X-Amz-Firehose-Access-Key', 'dev')],
    )

    assert response.status_code == 200
    assert response.json == {'status': 'received'}

    actual = mock_logger.call_args_list[0].args[0]
    expected = 'PinpointV2 delivery-status request: %s'
    assert actual == expected, 'The logger was not called with the expected message.'
