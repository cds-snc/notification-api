import pytest

from app import aws_pinpoint_client
from tests.conftest import set_config_values


def test_send_sms_sends_to_default_pool(notify_api, mocker, sample_template):
    boto_mock = mocker.patch.object(aws_pinpoint_client, "_client", create=True)
    mocker.patch.object(aws_pinpoint_client, "statsd_client", create=True)
    to = "6135555555"
    content = "foo"
    reference = "ref"

    with set_config_values(
        notify_api,
        {
            "AWS_PINPOINT_SC_POOL_ID": "sc_pool_id",
            "AWS_PINPOINT_DEFAULT_POOL_ID": "default_pool_id",
            "AWS_PINPOINT_CONFIGURATION_SET_NAME": "config_set_name",
            "AWS_PINPOINT_SC_TEMPLATE_IDS": [],
        },
    ):
        aws_pinpoint_client.send_sms(to, content, reference=reference, template_id=sample_template.id)

    boto_mock.send_text_message.assert_called_once_with(
        DestinationPhoneNumber="+16135555555",
        OriginationIdentity="default_pool_id",
        MessageBody=content,
        MessageType="TRANSACTIONAL",
        ConfigurationSetName="config_set_name",
    )


def test_send_sms_sends_to_shortcode_pool(notify_api, mocker, sample_template):
    boto_mock = mocker.patch.object(aws_pinpoint_client, "_client", create=True)
    mocker.patch.object(aws_pinpoint_client, "statsd_client", create=True)
    to = "6135555555"
    content = "foo"
    reference = "ref"

    with set_config_values(
        notify_api,
        {
            "AWS_PINPOINT_SC_POOL_ID": "sc_pool_id",
            "AWS_PINPOINT_DEFAULT_POOL_ID": "default_pool_id",
            "AWS_PINPOINT_CONFIGURATION_SET_NAME": "config_set_name",
            "AWS_PINPOINT_SC_TEMPLATE_IDS": [str(sample_template.id)],
        },
    ):
        with notify_api.app_context():
            aws_pinpoint_client.send_sms(to, content, reference=reference, template_id=sample_template.id)

    boto_mock.send_text_message.assert_called_once_with(
        DestinationPhoneNumber="+16135555555",
        OriginationIdentity="sc_pool_id",
        MessageBody=content,
        MessageType="TRANSACTIONAL",
        ConfigurationSetName="config_set_name",
    )


def test_send_sms_returns_raises_error_if_there_is_no_valid_number_is_found(notify_api, mocker):
    mocker.patch.object(aws_pinpoint_client, "_client", create=True)
    mocker.patch.object(aws_pinpoint_client, "statsd_client", create=True)

    to = ""
    content = reference = "foo"

    with pytest.raises(ValueError) as excinfo:
        aws_pinpoint_client.send_sms(to, content, reference)

    assert "No valid numbers found for SMS delivery" in str(excinfo.value)


# TODO: make sure fixed long code sends and sends to us numbers go through old SNS flow.
# That's not tested here.
