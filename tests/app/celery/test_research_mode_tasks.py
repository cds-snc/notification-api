import uuid
from datetime import datetime
from unittest.mock import ANY, call

import pytest
from freezegun import freeze_time

from app.aws.mocks import (
    ses_notification_callback,
    sns_failed_callback,
    sns_success_callback,
)
from app.celery.research_mode_tasks import send_email_response, send_sms_response
from app.config import QueueNames
from tests.conftest import Matcher

dvla_response_file_matcher = Matcher(
    "dvla_response_file",
    lambda x: "NOTIFY-20180125140000-RSP.TXT" < x <= "NOTIFY-20180125140030-RSP.TXT",
)


@pytest.mark.parametrize(
    "phone_number, sns_callback, sns_callback_args",
    [
        ("+15149301630", sns_success_callback, {}),
        ("+15149301631", sns_success_callback, {}),
        ("+15149301632", sns_failed_callback, {"provider_response": "Phone is currently unreachable/unavailable"}),
        ("+15149301633", sns_failed_callback, {"provider_response": "Phone carrier is currently unreachable/unavailable"}),
    ],
)
@freeze_time("2018-01-25 14:00:30")
def test_make_sns_success_callback(notify_api, mocker, phone_number, sns_callback, sns_callback_args):
    mock_task = mocker.patch("app.celery.research_mode_tasks.process_sns_results")
    some_ref = str(uuid.uuid4())
    now = datetime.now()
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

    send_sms_response("sns", phone_number, some_ref)

    mock_task.apply_async.assert_called_once_with(ANY, queue=QueueNames.RESEARCH_MODE)
    message_celery = mock_task.apply_async.call_args[0][0][0]
    sns_callback_args.update({"reference": some_ref, "destination": phone_number, "timestamp": timestamp})
    assert message_celery == sns_callback(**sns_callback_args)


def test_make_ses_callback(notify_api, mocker):
    mock_task = mocker.patch("app.celery.research_mode_tasks.process_ses_results")
    some_ref = str(uuid.uuid4())

    send_email_response(reference=some_ref, to="test@test.com")

    mock_task.apply_async.assert_called_once_with(ANY, queue=QueueNames.RESEARCH_MODE)
    assert mock_task.apply_async.call_args[0][0][0] == ses_notification_callback(some_ref)
