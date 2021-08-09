import json
import pytest

from app.celery.process_pinpoint_inbound_sms import CeleryEvent, process_pinpoint_inbound_sms
from app.dao.permissions_dao import permission_dao
from app.feature_flags import FeatureFlag
from app.models import QUEUE_CHANNEL_TYPE, INBOUND_SMS_CALLBACK_TYPE, PLATFORM_ADMIN, Permission
from tests.app.factories.feature_flag import mock_feature_flag
from botocore.stub import Stubber, ANY
from app import sqs_client


@pytest.fixture
def pinpoint_inbound_sms_toggle_enabled(mocker):
    mock_feature_flag(mocker, FeatureFlag.PINPOINT_INBOUND_SMS_ENABLED, 'True')


@pytest.fixture()
def sqs_stub():
    with Stubber(sqs_client._client) as stubber:
        yield stubber
        stubber.assert_no_pending_responses()


class AnySms(object):
    def __init__(
            self, id=ANY, source_number=ANY, destination_number=ANY, message=ANY, date_received=ANY, sms_sender_id=ANY
    ):
        self.id = id
        self.source_number = source_number
        self.destination_number = destination_number
        self.message = message
        self.date_received = date_received
        self.sms_sender_id = sms_sender_id

    def __eq__(self, other):
        other_dict = json.loads(other)

        return (
            other_dict["source_number"] == self.source_number
            and other_dict["destination_number"] == self.destination_number
            and other_dict["message"] == self.message
            and other_dict["sms_sender_id"] == self.sms_sender_id
        )


def test_sqs_callback(sample_service_full_permissions, admin_request, pinpoint_inbound_sms_toggle_enabled, sqs_stub):
    sample_service = sample_service_full_permissions
    user = sample_service.users[0]
    permission_dao.set_user_service_permission(
        user,
        sample_service,
        [Permission(
            service_id=sample_service.id,
            user_id=user.id,
            permission=PLATFORM_ADMIN
        )])
    data = {
        "url": "https://some.queue/inbound-sms-endpoint",
        "updated_by_id": str(sample_service.users[0].id),
        "callback_type": INBOUND_SMS_CALLBACK_TYPE,
        "callback_channel": QUEUE_CHANNEL_TYPE
    }

    admin_request.post(
        'service_callback.create_service_callback',
        service_id=sample_service.id,
        _data=data,
        _expected_status=201
    )

    message = {
        "messageBody": "foo",
        "destinationNumber": "12345",  # set by sample_service_full_permissions
        "originationNumber": "123",
        "inboundMessageId": "bar"
    }
    event: CeleryEvent = {"Message": json.dumps(message)}

    sqs_stub.add_response(
        'send_message',
        expected_params={
            'QueueUrl': data["url"],
            'MessageBody': AnySms(
                message=message["messageBody"],
                source_number=message["originationNumber"],
                destination_number=message["destinationNumber"],
                sms_sender_id=None
            ),
            'MessageAttributes': ANY
        },
        service_response={'MessageId': "foo"}
    )

    process_pinpoint_inbound_sms(event)
