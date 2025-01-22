import datetime
import uuid
from unittest.mock import call

import pytest
from boto3.exceptions import Boto3Error
from freezegun import freeze_time
from notifications_utils.recipients import (
    validate_and_format_email_address,
    validate_and_format_phone_number,
)
from sqlalchemy.exc import SQLAlchemyError

from app.celery.utils import CeleryParams
from app.config import QueueNames
from app.dao.service_sms_sender_dao import dao_update_service_sms_sender
from app.models import (  # ApiKey,
    BULK,
    NORMAL,
    PRIORITY,
    Notification,
    NotificationHistory,
    ScheduledNotification,
    Template,
)
from app.notifications.process_notifications import (
    choose_queue,
    create_content_for_notification,
    db_save_and_send_notification,
    persist_notification,
    persist_notifications,
    persist_scheduled_notification,
    send_notification_to_queue,
    simulated_recipient,
    transform_notification,
)
from app.v2.errors import BadRequestError
from tests.app.conftest import create_sample_api_key
from tests.app.db import create_service_sms_sender
from tests.conftest import set_config


class TestContentCreation:
    def test_create_content_for_notification_passes(self, sample_email_template):
        template = Template.query.get(sample_email_template.id)
        content = create_content_for_notification(template, None)
        assert str(content) == template.content

    def test_create_content_for_notification_with_placeholders_passes(
        self,
        sample_template_with_placeholders,
    ):
        template = Template.query.get(sample_template_with_placeholders.id)
        content = create_content_for_notification(template, {"name": "Bobby"})
        assert content.content == template.content
        assert "Bobby" in str(content)

    def test_create_content_for_notification_fails_with_missing_personalisation(
        self,
        sample_template_with_placeholders,
    ):
        template = Template.query.get(sample_template_with_placeholders.id)
        with pytest.raises(BadRequestError):
            create_content_for_notification(template, None)

    def test_create_content_for_notification_allows_additional_personalisation(
        self,
        sample_template_with_placeholders,
    ):
        template = Template.query.get(sample_template_with_placeholders.id)
        create_content_for_notification(template, {"name": "Bobby", "Additional placeholder": "Data"})


class TestPersistNotification:
    def test_persists_notification_throws_exception_when_missing_template(self, sample_api_key):
        assert Notification.query.count() == 0
        assert NotificationHistory.query.count() == 0
        with pytest.raises(SQLAlchemyError):
            persist_notifications(
                [
                    dict(
                        template_id=None,
                        template_version=None,
                        recipient="+16502532222",
                        service=sample_api_key.service,
                        personalisation=None,
                        notification_type="sms",
                        api_key_id=sample_api_key.id,
                        key_type=sample_api_key.key_type,
                    )
                ]
            )
        assert Notification.query.count() == 0
        assert NotificationHistory.query.count() == 0

    def test_persist_notifications_does_not_increment_cache_if_test_key(
        self, notify_db, notify_db_session, sample_template, sample_job, mocker
    ):
        api_key = create_sample_api_key(
            notify_db=notify_db,
            notify_db_session=notify_db_session,
            service=sample_template.service,
            key_type="test",
        )
        mocker.patch("app.notifications.process_notifications.redis_store.get", return_value="cache")
        mocker.patch(
            "app.notifications.process_notifications.redis_store.get_all_from_hash",
            return_value="cache",
        )
        daily_limit_cache = mocker.patch("app.notifications.process_notifications.redis_store.incr")
        template_usage_cache = mocker.patch("app.notifications.process_notifications.redis_store.increment_hash_value")
        mocker.patch("app.notifications.process_notifications.dao_get_template_by_id", return_value=sample_template)
        mocker.patch("app.notifications.process_notifications.dao_fetch_service_by_id", return_value=sample_template.service)
        mocker.patch("app.notifications.process_notifications.choose_queue", return_value="sms_normal_queue")

        assert Notification.query.count() == 0
        assert NotificationHistory.query.count() == 0
        persist_notifications(
            [
                dict(
                    template_id=sample_template.id,
                    template_version=sample_template.version,
                    recipient="+16502532222",
                    service=sample_template.service,
                    personalisation={},
                    notification_type="sms",
                    api_key_id=api_key.id,
                    key_type=api_key.key_type,
                    job_id=sample_job.id,
                    job_row_number=100,
                    reference="ref",
                )
            ]
        )
        assert Notification.query.count() == 1
        assert not daily_limit_cache.called
        assert not template_usage_cache.called

    @freeze_time("2016-01-01 11:09:00.061258")
    def test_persist_notifications_with_optionals(self, client, sample_job, sample_api_key, mocker, sample_template):
        assert Notification.query.count() == 0
        assert NotificationHistory.query.count() == 0

        mocked_redis = mocker.patch("app.notifications.process_notifications.redis_store.get")
        mocker.patch("app.notifications.process_notifications.dao_get_template_by_id", return_value=sample_template)
        mocker.patch("app.notifications.process_notifications.dao_fetch_service_by_id", return_value=sample_template.service)
        mocker.patch("app.notifications.process_notifications.choose_queue", return_value="sms_normal_queue")
        n_id = uuid.uuid4()
        created_at = datetime.datetime(2016, 11, 11, 16, 8, 18)

        persist_notifications(
            [
                dict(
                    template_id=sample_job.template.id,
                    template_version=sample_job.template.version,
                    recipient="+16502532222",
                    service=sample_job.service,
                    personalisation=None,
                    notification_type="sms",
                    api_key_id=sample_api_key.id,
                    key_type=sample_api_key.key_type,
                    created_at=created_at,
                    job_id=sample_job.id,
                    job_row_number=10,
                    client_reference="ref from client",
                    notification_id=n_id,
                    created_by_id=sample_job.created_by_id,
                )
            ]
        )
        assert Notification.query.count() == 1
        assert NotificationHistory.query.count() == 0
        persisted_notification = Notification.query.all()[0]
        assert persisted_notification.id == n_id
        persisted_notification.job_id == sample_job.id
        assert persisted_notification.job_row_number == 10
        assert persisted_notification.created_at == created_at
        assert persisted_notification.client_reference == "ref from client"
        assert persisted_notification.reference is None
        assert persisted_notification.international is False
        assert persisted_notification.phone_prefix == "1"
        assert persisted_notification.rate_multiplier == 1
        assert persisted_notification.created_by_id == sample_job.created_by_id
        assert not persisted_notification.reply_to_text

        expected_redis_calls = [
            call(str(sample_job.service_id) + "-2016-01-01-count"),
        ]
        assert mocked_redis.call_count == len(expected_redis_calls)
        assert mocked_redis.call_args_list == expected_redis_calls

    @freeze_time("2016-01-01 11:09:00.061258")
    def test_persist_notifications_doesnt_touch_cache_for_old_keys_that_dont_exist(self, sample_template, sample_api_key, mocker):
        mock_incr = mocker.patch("app.notifications.process_notifications.redis_store.incr")
        mocker.patch("app.notifications.process_notifications.redis_store.get", return_value=None)
        mocker.patch(
            "app.notifications.process_notifications.redis_store.get_all_from_hash",
            return_value=None,
        )
        mocker.patch("app.notifications.process_notifications.dao_get_template_by_id", return_value=sample_template)
        mocker.patch("app.notifications.process_notifications.dao_fetch_service_by_id", return_value=sample_template.service)
        persist_notifications(
            [
                dict(
                    template_id=sample_template.id,
                    template_version=sample_template.version,
                    recipient="+16502532222",
                    service=sample_template.service,
                    personalisation={},
                    notification_type="sms",
                    api_key_id=sample_api_key.id,
                    key_type=sample_api_key.key_type,
                    reference="ref",
                )
            ]
        )
        mock_incr.assert_not_called()

    @freeze_time("2016-01-01 11:09:00.061258")
    def test_persist_notifications_increments_cache_if_key_exists(self, sample_template, sample_api_key, mocker):
        mock_incr = mocker.patch("app.notifications.process_notifications.redis_store.incr")
        mocker.patch("app.notifications.process_notifications.redis_store.get", return_value=1)
        mocker.patch(
            "app.notifications.process_notifications.redis_store.get_all_from_hash",
            return_value={sample_template.id, 1},
        )
        mocker.patch("app.notifications.process_notifications.dao_get_template_by_id", return_value=sample_template)
        mocker.patch("app.notifications.process_notifications.dao_fetch_service_by_id", return_value=sample_template.service)
        mocker.patch("app.notifications.process_notifications.choose_queue", return_value="sms_normal_queue")

        persist_notifications(
            [
                dict(
                    template_id=sample_template.id,
                    template_version=sample_template.version,
                    recipient="+16502532222",
                    service=sample_template.service,
                    personalisation={},
                    notification_type="sms",
                    api_key_id=sample_api_key.id,
                    key_type=sample_api_key.key_type,
                    reference="ref2",
                )
            ]
        )

        mock_incr.assert_called_once_with(
            str(sample_template.service_id) + "-2016-01-01-count",
        )

    @pytest.mark.parametrize(
        "recipient, expected_international, expected_prefix, expected_units",
        [
            ("6502532222", False, "1", 1),  # NA
            ("+16502532222", False, "1", 1),  # NA
            ("+79587714230", True, "7", 1),  # Russia
            ("+360623400400", True, "36", 3),
        ],  # Hungary
    )
    def test_persist_notifications_with_international_info_stores_correct_info(
        self,
        sample_job,
        sample_api_key,
        mocker,
        recipient,
        expected_international,
        expected_prefix,
        expected_units,
    ):
        persist_notifications(
            [
                dict(
                    template_id=sample_job.template.id,
                    template_version=sample_job.template.version,
                    recipient=recipient,
                    service=sample_job.service,
                    personalisation=None,
                    notification_type="sms",
                    api_key_id=sample_api_key.id,
                    key_type=sample_api_key.key_type,
                    job_id=sample_job.id,
                    job_row_number=10,
                    client_reference="ref from client",
                )
            ]
        )
        persisted_notification = Notification.query.all()[0]

        assert persisted_notification.international is expected_international
        assert persisted_notification.phone_prefix == expected_prefix
        assert persisted_notification.rate_multiplier == expected_units

    def test_persist_notification_with_international_info_does_not_store_for_email(self, sample_job, sample_api_key, mocker):
        persist_notifications(
            [
                dict(
                    template_id=sample_job.template.id,
                    template_version=sample_job.template.version,
                    recipient="foo@bar.com",
                    service=sample_job.service,
                    personalisation=None,
                    notification_type="email",
                    api_key_id=sample_api_key.id,
                    key_type=sample_api_key.key_type,
                    job_id=sample_job.id,
                    job_row_number=10,
                    client_reference="ref from client",
                )
            ]
        )
        persisted_notification = Notification.query.all()[0]

        assert persisted_notification.international is False
        assert persisted_notification.phone_prefix is None
        assert persisted_notification.rate_multiplier is None

    @pytest.mark.parametrize(
        "recipient, expected_recipient_normalised",
        [
            ("6502532222", "+16502532222"),
            ("  6502532223", "+16502532223"),
            ("6502532223", "+16502532223"),
        ],
    )
    def test_persist_sms_notifications_stores_normalised_number(
        self, sample_job, sample_api_key, mocker, recipient, expected_recipient_normalised
    ):
        persist_notifications(
            [
                dict(
                    template_id=sample_job.template.id,
                    template_version=sample_job.template.version,
                    recipient=recipient,
                    service=sample_job.service,
                    personalisation=None,
                    notification_type="sms",
                    api_key_id=sample_api_key.id,
                    key_type=sample_api_key.key_type,
                    job_id=sample_job.id,
                )
            ]
        )
        persisted_notification = Notification.query.all()[0]

        assert persisted_notification.to == recipient
        assert persisted_notification.normalised_to == expected_recipient_normalised

    @pytest.mark.parametrize(
        "recipient, expected_recipient_normalised",
        [("FOO@bar.com", "foo@bar.com"), ("BAR@foo.com", "bar@foo.com")],
    )
    def test_persist_email_notifications_stores_normalised_email(
        self, sample_job, sample_api_key, mocker, recipient, expected_recipient_normalised
    ):
        persist_notifications(
            [
                dict(
                    template_id=sample_job.template.id,
                    template_version=sample_job.template.version,
                    recipient=recipient,
                    service=sample_job.service,
                    personalisation=None,
                    notification_type="email",
                    api_key_id=sample_api_key.id,
                    key_type=sample_api_key.key_type,
                    job_id=sample_job.id,
                )
            ]
        )
        persisted_notification = Notification.query.all()[0]

        assert persisted_notification.to == recipient
        assert persisted_notification.normalised_to == expected_recipient_normalised

    def test_persist_notifications_list(self, sample_job, sample_api_key, notify_db_session):
        persist_notifications(
            [
                dict(
                    template_id=sample_job.template.id,
                    template_version=sample_job.template.version,
                    recipient="foo@bar.com",
                    service=sample_job.service,
                    personalisation=None,
                    notification_type="email",
                    api_key_id=sample_api_key.id,
                    key_type=sample_api_key.key_type,
                    job_id=sample_job.id,
                    job_row_number=10,
                    client_reference="ref from client",
                ),
                dict(
                    template_id=sample_job.template.id,
                    template_version=sample_job.template.version,
                    recipient="foo2@bar.com",
                    service=sample_job.service,
                    personalisation=None,
                    notification_type="email",
                    api_key_id=sample_api_key.id,
                    key_type=sample_api_key.key_type,
                    job_id=sample_job.id,
                    job_row_number=10,
                    client_reference="ref from client",
                ),
            ]
        )
        persisted_notification = Notification.query.all()

        assert persisted_notification[0].to == "foo@bar.com"
        assert persisted_notification[1].to == "foo2@bar.com"
        assert persisted_notification[0].service == sample_job.service

        # Test that the api key last_used_timestamp got updated

        # incident fix - should revert this later
        # api_key = ApiKey.query.get(sample_api_key.id)
        # assert api_key.last_used_timestamp is not None

    def test_persist_notifications_reply_to_text_is_original_value_if_sender_is_changed_later(
        self, sample_template, sample_api_key, mocker
    ):
        mocker.patch("app.notifications.process_notifications.redis_store.incr")
        mocker.patch("app.notifications.process_notifications.redis_store.get", return_value=1)
        mocker.patch(
            "app.notifications.process_notifications.redis_store.get_all_from_hash",
            return_value={sample_template.id, 1},
        )
        mocker.patch("app.notifications.process_notifications.dao_get_template_by_id", return_value=sample_template)
        mocker.patch("app.notifications.process_notifications.dao_fetch_service_by_id", return_value=sample_template.service)
        mocker.patch("app.notifications.process_notifications.choose_queue", return_value="sms_normal_queue")

        sms_sender = create_service_sms_sender(service=sample_template.service, sms_sender="123456", is_default=False)
        persist_notifications(
            [
                dict(
                    template_id=sample_template.id,
                    template_version=sample_template.version,
                    recipient="+16502532222",
                    service=sample_template.service,
                    personalisation={},
                    notification_type="sms",
                    api_key_id=sample_api_key.id,
                    key_type=sample_api_key.key_type,
                    reference="ref2",
                    reply_to_text=sms_sender.sms_sender,
                )
            ]
        )
        persisted_notification = Notification.query.all()[0]
        assert persisted_notification.reply_to_text == "123456"

        dao_update_service_sms_sender(
            service_id=sample_template.service_id,
            service_sms_sender_id=sms_sender.id,
            is_default=sms_sender.is_default,
            sms_sender="updated",
        )
        persisted_notification = Notification.query.all()[0]
        assert persisted_notification.reply_to_text == "123456"


class TestSendNotificationQueue:
    @pytest.mark.parametrize(
        ("research_mode, requested_queue, notification_type, key_type, reply_to_text, expected_queue, expected_task"),
        [
            (True, None, "sms", "normal", None, "research-mode-tasks", "deliver_sms"),
            (True, None, "email", "normal", None, "research-mode-tasks", "deliver_email"),
            (True, None, "email", "team", None, "research-mode-tasks", "deliver_email"),
            (
                True,
                None,
                "letter",
                "normal",
                None,
                "research-mode-tasks",
                "letters_pdf_tasks.create_letters_pdf",
            ),
            (
                True,
                None,
                "sms",
                "normal",
                "+14383898585",
                "send-throttled-sms-tasks",
                "deliver_throttled_sms",
            ),
            (False, None, "sms", "normal", None, QueueNames.SEND_SMS_MEDIUM, "deliver_sms"),
            (False, None, "email", "normal", None, QueueNames.SEND_EMAIL_MEDIUM, "deliver_email"),
            (False, None, "sms", "team", None, QueueNames.SEND_SMS_MEDIUM, "deliver_sms"),
            (
                False,
                None,
                "letter",
                "normal",
                None,
                "create-letters-pdf-tasks",
                "letters_pdf_tasks.create_letters_pdf",
            ),
            (False, None, "sms", "test", None, "research-mode-tasks", "deliver_sms"),
            (
                False,
                None,
                "sms",
                "normal",
                "+14383898585",
                "send-throttled-sms-tasks",
                "deliver_throttled_sms",
            ),
            (
                True,
                "notify-internal-tasks",
                "email",
                "normal",
                None,
                "research-mode-tasks",
                "deliver_email",
            ),
            (
                False,
                "notify-internal-tasks",
                "sms",
                "normal",
                None,
                "notify-internal-tasks",
                "deliver_sms",
            ),
            (
                False,
                "notify-internal-tasks",
                "email",
                "normal",
                None,
                "notify-internal-tasks",
                "deliver_email",
            ),
            (
                False,
                "notify-internal-tasks",
                "sms",
                "test",
                None,
                "research-mode-tasks",
                "deliver_sms",
            ),
            (
                False,
                "notify-internal-tasks",
                "sms",
                "normal",
                "+14383898585",
                "send-throttled-sms-tasks",
                "deliver_throttled_sms",
            ),
        ],
    )
    def test_send_notification_to_queue(
        self,
        notify_db,
        notify_db_session,
        research_mode,
        requested_queue,
        notification_type,
        key_type,
        reply_to_text,
        expected_queue,
        expected_task,
        mocker,
    ):
        if "." not in expected_task:
            expected_task = f"provider_tasks.{expected_task}"
        mocked = mocker.patch(f"app.celery.{expected_task}.apply_async")
        notification = Notification(
            id=uuid.uuid4(),
            key_type=key_type,
            notification_type=notification_type,
            created_at=datetime.datetime(2016, 11, 11, 16, 8, 18),
            reply_to_text=reply_to_text,
        )

        send_notification_to_queue(notification=notification, research_mode=research_mode, queue=requested_queue)

        mocked.assert_called_once_with([str(notification.id)], queue=expected_queue)

    def test_send_notification_to_queue_throws_exception_deletes_notification(self, sample_notification, mocker):
        mocked = mocker.patch(
            "app.celery.provider_tasks.deliver_sms.apply_async",
            side_effect=Boto3Error("EXPECTED"),
        )
        with pytest.raises(Boto3Error):
            send_notification_to_queue(sample_notification, False)
        mocked.assert_called_once_with([(str(sample_notification.id))], queue=QueueNames.SEND_SMS_MEDIUM)

        assert Notification.query.count() == 0
        assert NotificationHistory.query.count() == 0


class TestSimulatedRecipient:
    @pytest.mark.parametrize(
        "to_address, notification_type, expected",
        [
            ("+16132532222", "sms", True),
            ("+16132532223", "sms", True),
            ("6132532222", "sms", True),
            ("simulate-delivered@notification.canada.ca", "email", True),
            ("simulate-delivered-2@notification.canada.ca", "email", True),
            ("simulate-delivered-3@notification.canada.ca", "email", True),
            ("6132532225", "sms", False),
            ("valid_email@test.com", "email", False),
        ],
    )
    def test_simulated_recipient(self, notify_api, to_address, notification_type, expected):
        """
        The values where the expected = 'research-mode' are listed in the config['SIMULATED_EMAIL_ADDRESSES']
        and config['SIMULATED_SMS_NUMBERS']. These values should result in using the research mode queue.
        SIMULATED_EMAIL_ADDRESSES = (
            'simulate-delivered@notification.canada.ca',
            'simulate-delivered-2@notification.canada.ca',
            'simulate-delivered-2@notification.canada.ca'
        )
        SIMULATED_SMS_NUMBERS = ('6132532222', '+16132532222', '+16132532223')
        """
        formatted_address = None

        if notification_type == "email":
            formatted_address = validate_and_format_email_address(to_address)
        else:
            formatted_address = validate_and_format_phone_number(to_address)

        is_simulated_address = simulated_recipient(formatted_address, notification_type)

        assert is_simulated_address == expected


# This test assumes the local timezone is EST
class TestScheduledNotification:
    def test_persist_scheduled_notification(self, sample_notification):
        persist_scheduled_notification(sample_notification.id, "2017-05-12 14:15")
        scheduled_notification = ScheduledNotification.query.all()
        assert len(scheduled_notification) == 1
        assert scheduled_notification[0].notification_id == sample_notification.id
        assert scheduled_notification[0].scheduled_for == datetime.datetime(2017, 5, 12, 18, 15)


class TestChooseQueue:
    @pytest.mark.parametrize(
        ("research_mode, requested_queue, notification_type, key_type, reply_to_text, expected_queue"),
        [
            (True, None, "sms", "normal", None, "research-mode-tasks"),
            (True, None, "email", "normal", None, "research-mode-tasks"),
            (True, None, "email", "team", None, "research-mode-tasks"),
            (
                True,
                None,
                "letter",
                "normal",
                None,
                "research-mode-tasks",
            ),
            (
                True,
                None,
                "sms",
                "normal",
                "+14383898585",
                "send-throttled-sms-tasks",
            ),
            (False, None, "sms", "normal", None, QueueNames.SEND_SMS_MEDIUM),
            (False, None, "email", "normal", None, QueueNames.SEND_EMAIL_MEDIUM),
            (False, None, "sms", "team", None, QueueNames.SEND_SMS_MEDIUM),
            (
                False,
                None,
                "letter",
                "normal",
                None,
                "create-letters-pdf-tasks",
            ),
            (False, None, "sms", "test", None, "research-mode-tasks"),
            (
                False,
                None,
                "sms",
                "normal",
                "+14383898585",
                "send-throttled-sms-tasks",
            ),
            (
                True,
                "notify-internal-tasks",
                "email",
                "normal",
                None,
                "research-mode-tasks",
            ),
            (
                False,
                "notify-internal-tasks",
                "sms",
                "normal",
                None,
                "notify-internal-tasks",
            ),
            (
                False,
                "notify-internal-tasks",
                "email",
                "normal",
                None,
                "notify-internal-tasks",
            ),
            (
                False,
                "notify-internal-tasks",
                "sms",
                "test",
                None,
                "research-mode-tasks",
            ),
            (
                False,
                "notify-internal-tasks",
                "sms",
                "normal",
                "+14383898585",
                "send-throttled-sms-tasks",
            ),
        ],
    )
    def test_choose_queue(
        self,
        sample_template,
        sample_api_key,
        sample_job,
        research_mode,
        requested_queue,
        notification_type,
        key_type,
        reply_to_text,
        expected_queue,
    ):
        notification = Notification(
            id=uuid.uuid4(),
            template_id=sample_template.id,
            template_version=sample_template.version,
            service=sample_template.service,
            personalisation={},
            notification_type=notification_type,
            api_key_id=sample_api_key.id,
            key_type=key_type,
            job_id=sample_job.id,
            job_row_number=100,
            reference="ref",
            reply_to_text=reply_to_text,
            to="+16502532222",
            created_at=datetime.datetime(2016, 11, 11, 16, 8, 18),
        )

        assert choose_queue(notification, research_mode, requested_queue) == expected_queue


class TestTransformNotification:
    def test_transform_notification_with_optionals(self, sample_job, sample_api_key, notify_db_session):
        assert Notification.query.count() == 0
        assert NotificationHistory.query.count() == 0

        n_id = uuid.uuid4()
        created_at = datetime.datetime(2016, 11, 11, 16, 8, 18)
        notification = transform_notification(
            template_id=sample_job.template.id,
            template_version=sample_job.template.version,
            recipient="+16502532222",
            service=sample_job.service,
            personalisation=None,
            notification_type="sms",
            api_key_id=sample_api_key.id,
            key_type=sample_api_key.key_type,
            created_at=created_at,
            job_id=sample_job.id,
            job_row_number=10,
            client_reference="ref from client",
            notification_id=n_id,
            created_by_id=sample_job.created_by_id,
        )
        assert notification.id == n_id
        assert notification.job_id == sample_job.id
        assert notification.job_row_number == 10
        assert notification.created_at == created_at
        assert notification.client_reference == "ref from client"
        assert notification.reference is None
        assert notification.international is False
        assert notification.phone_prefix == "1"
        assert notification.rate_multiplier == 1
        assert notification.created_by_id == sample_job.created_by_id
        assert not notification.reply_to_text

    @pytest.mark.parametrize(
        "recipient, expected_international, expected_prefix, expected_units",
        [
            ("6502532222", False, "1", 1),  # NA
            ("+16502532222", False, "1", 1),  # NA
            ("+79587714230", True, "7", 1),  # Russia
            ("+360623400400", True, "36", 3),
        ],  # Hungary
    )
    def test_transform_notification_with_international_info_stores_correct_info(
        self,
        sample_job,
        sample_api_key,
        mocker,
        recipient,
        expected_international,
        expected_prefix,
        expected_units,
    ):
        notification = transform_notification(
            template_id=sample_job.template.id,
            template_version=sample_job.template.version,
            recipient=recipient,
            service=sample_job.service,
            personalisation=None,
            notification_type="sms",
            api_key_id=sample_api_key.id,
            key_type=sample_api_key.key_type,
            job_id=sample_job.id,
            job_row_number=10,
            client_reference="ref from client",
        )

        assert notification.international is expected_international
        assert notification.phone_prefix == expected_prefix
        assert notification.rate_multiplier == expected_units

    def test_transform_notification_with_international_info_does_not_store_for_email(self, sample_job, sample_api_key, mocker):
        notification = transform_notification(
            template_id=sample_job.template.id,
            template_version=sample_job.template.version,
            recipient="foo@bar.com",
            service=sample_job.service,
            personalisation=None,
            notification_type="email",
            api_key_id=sample_api_key.id,
            key_type=sample_api_key.key_type,
            job_id=sample_job.id,
            job_row_number=10,
            client_reference="ref from client",
        )
        assert notification.international is False
        assert notification.phone_prefix is None
        assert notification.rate_multiplier is None

    @pytest.mark.parametrize(
        "recipient, expected_recipient_normalised",
        [
            ("6502532222", "+16502532222"),
            ("  6502532223", "+16502532223"),
            ("6502532223", "+16502532223"),
        ],
    )
    def test_transform_sms_notification_stores_normalised_number(
        self, sample_job, sample_api_key, mocker, recipient, expected_recipient_normalised
    ):
        notification = transform_notification(
            template_id=sample_job.template.id,
            template_version=sample_job.template.version,
            recipient=recipient,
            service=sample_job.service,
            personalisation=None,
            notification_type="sms",
            api_key_id=sample_api_key.id,
            key_type=sample_api_key.key_type,
            job_id=sample_job.id,
        )

        assert notification.to == recipient
        assert notification.normalised_to == expected_recipient_normalised

    @pytest.mark.parametrize(
        "recipient, expected_recipient_normalised",
        [("FOO@bar.com", "foo@bar.com"), ("BAR@foo.com", "bar@foo.com")],
    )
    def test_transform_email_notification_stores_normalised_email(
        self, sample_job, sample_api_key, mocker, recipient, expected_recipient_normalised
    ):
        persist_notification(
            template_id=sample_job.template.id,
            template_version=sample_job.template.version,
            recipient=recipient,
            service=sample_job.service,
            personalisation=None,
            notification_type="email",
            api_key_id=sample_api_key.id,
            key_type=sample_api_key.key_type,
            job_id=sample_job.id,
        )
        persisted_notification = Notification.query.all()[0]

        assert persisted_notification.to == recipient
        assert persisted_notification.normalised_to == expected_recipient_normalised
        # incident fix - should revert this later
        # api_key = ApiKey.query.get(sample_api_key.id)
        # assert api_key.last_used_timestamp is not None


class TestDBSaveAndSendNotification:
    @freeze_time("2016-01-01 11:09:00.061258")
    def test_db_save_and_send_notification_saves_to_db(self, client, sample_template, sample_api_key, sample_job, mocker):
        mocked_redis = mocker.patch("app.notifications.process_notifications.redis_store.get")
        mocker.patch("app.celery.provider_tasks.deliver_sms.apply_async")
        assert Notification.query.count() == 0
        assert NotificationHistory.query.count() == 0

        notification = Notification(
            id=uuid.uuid4(),
            template_id=sample_template.id,
            template_version=sample_template.version,
            service=sample_template.service,
            personalisation={},
            notification_type="sms",
            api_key_id=sample_api_key.id,
            key_type=sample_api_key.key_type,
            job_id=sample_job.id,
            job_row_number=100,
            reference="ref",
            reply_to_text=sample_template.service.get_default_sms_sender(),
            to="+16502532222",
            created_at=datetime.datetime(2016, 11, 11, 16, 8, 18),
        )
        db_save_and_send_notification(notification)
        assert Notification.query.get(notification.id) is not None

        notification_from_db = Notification.query.one()

        assert notification_from_db.id == notification.id
        assert notification_from_db.template_id == notification.template_id
        assert notification_from_db.template_version == notification.template_version
        assert notification_from_db.api_key_id == notification.api_key_id
        assert notification_from_db.key_type == notification.key_type
        assert notification_from_db.key_type == notification.key_type
        assert notification_from_db.billable_units == notification.billable_units
        assert notification_from_db.notification_type == notification.notification_type
        assert notification_from_db.created_at == notification.created_at
        assert not notification_from_db.sent_at
        assert notification_from_db.updated_at == notification.updated_at
        assert notification_from_db.status == notification.status
        assert notification_from_db.reference == notification.reference
        assert notification_from_db.client_reference == notification.client_reference
        assert notification_from_db.created_by_id == notification.created_by_id
        assert notification_from_db.reply_to_text == sample_template.service.get_default_sms_sender()
        expected_redis_calls = [
            call(str(sample_job.service_id) + "-2016-01-01-count"),
        ]
        assert mocked_redis.call_count == len(expected_redis_calls)
        assert mocked_redis.call_args_list == expected_redis_calls

    @pytest.mark.parametrize(
        ("notification_type, key_type, reply_to_text, expected_queue, expected_task"),
        [
            ("sms", "normal", None, "research-mode-tasks", "deliver_sms"),
            ("email", "normal", None, "research-mode-tasks", "deliver_email"),
            ("email", "team", None, "research-mode-tasks", "deliver_email"),
            (
                "sms",
                "normal",
                "+14383898585",
                "send-throttled-sms-tasks",
                "deliver_throttled_sms",
            ),
            ("sms", "normal", None, QueueNames.SEND_SMS_MEDIUM, "deliver_sms"),
            ("email", "normal", None, QueueNames.SEND_EMAIL_MEDIUM, "deliver_email"),
            ("sms", "team", None, QueueNames.SEND_SMS_MEDIUM, "deliver_sms"),
            ("sms", "test", None, "research-mode-tasks", "deliver_sms"),
            (
                "sms",
                "normal",
                "+14383898585",
                "send-throttled-sms-tasks",
                "deliver_throttled_sms",
            ),
            (
                "email",
                "normal",
                None,
                "research-mode-tasks",
                "deliver_email",
            ),
            (
                "sms",
                "normal",
                None,
                "notify-internal-tasks",
                "deliver_sms",
            ),
            (
                "email",
                "normal",
                None,
                "notify-internal-tasks",
                "deliver_email",
            ),
            (
                "sms",
                "test",
                None,
                "research-mode-tasks",
                "deliver_sms",
            ),
            (
                "sms",
                "normal",
                "+14383898585",
                "send-throttled-sms-tasks",
                "deliver_throttled_sms",
            ),
        ],
    )
    def test_db_save_and_send_notification_sends_to_queue(
        self,
        sample_template,
        notify_db,
        notify_db_session,
        notification_type,
        key_type,
        reply_to_text,
        expected_queue,
        expected_task,
        mocker,
    ):
        if "." not in expected_task:
            expected_task = f"provider_tasks.{expected_task}"
        mocked = mocker.patch(f"app.celery.{expected_task}.apply_async")
        notification = Notification(
            id=uuid.uuid4(),
            to="joe@blow.com",
            template_id=sample_template.id,
            template_version=sample_template.version,
            key_type=key_type,
            notification_type=notification_type,
            created_at=datetime.datetime(2016, 11, 11, 16, 8, 18),
            reply_to_text=reply_to_text,
            queue_name=expected_queue,
        )

        db_save_and_send_notification(notification=notification)

        mocked.assert_called_once_with([str(notification.id)], queue=expected_queue)

    def test_db_save_and_send_notification_throws_exception_deletes_notification(
        self, sample_template, sample_api_key, sample_job, mocker
    ):
        mocked = mocker.patch(
            "app.celery.provider_tasks.deliver_sms.apply_async",
            side_effect=Boto3Error("EXPECTED"),
        )
        notification = Notification(
            id=uuid.uuid4(),
            template_id=sample_template.id,
            template_version=sample_template.version,
            service=sample_template.service,
            personalisation={},
            notification_type="sms",
            api_key_id=sample_api_key.id,
            key_type=sample_api_key.key_type,
            job_id=sample_job.id,
            job_row_number=100,
            reference="ref",
            reply_to_text=sample_template.service.get_default_sms_sender(),
            to="+16502532222",
            created_at=datetime.datetime(2016, 11, 11, 16, 8, 18),
            queue_name=QueueNames.SEND_SMS_MEDIUM,
        )

        with pytest.raises(Boto3Error):
            db_save_and_send_notification(notification)
        mocked.assert_called_once_with([(str(notification.id))], queue=QueueNames.SEND_SMS_MEDIUM)

        assert Notification.query.count() == 0
        assert NotificationHistory.query.count() == 0

    @pytest.mark.parametrize(
        ("process_type, expected_retry_period"),
        [
            (BULK, CeleryParams.RETRY_PERIODS[BULK]),
            (NORMAL, CeleryParams.RETRY_PERIODS[NORMAL]),
            (PRIORITY, CeleryParams.RETRY_PERIODS[PRIORITY]),
        ],
    )
    def test_retry_task_parameters(self, notify_api, process_type, expected_retry_period):
        with notify_api.app_context():
            params = CeleryParams.retry(process_type)

        assert params["queue"] == QueueNames.RETRY
        assert params["countdown"] == expected_retry_period

    @pytest.mark.parametrize(
        ("process_type"),
        [(BULK), (NORMAL), (PRIORITY), (None)],
    )
    def test_retry_task_parameters_with_countdown_override(self, notify_api, process_type):
        with notify_api.app_context():
            params = CeleryParams.retry(process_type, countdown=-1)

        assert params["queue"] == QueueNames.RETRY
        assert params["countdown"] == -1

    @pytest.mark.parametrize(
        ("process_type, expected_retry_period"),
        [
            (BULK, CeleryParams.RETRY_PERIODS[BULK]),
            (NORMAL, CeleryParams.RETRY_PERIODS[NORMAL]),
            (PRIORITY, CeleryParams.RETRY_PERIODS[PRIORITY]),
            (None, CeleryParams.RETRY_PERIODS[PRIORITY]),
        ],
    )
    def test_retry_task_parameters_with_ff_off(self, notify_api, process_type, expected_retry_period):
        with notify_api.app_context(), set_config(notify_api, "FF_CELERY_CUSTOM_TASK_PARAMS", False):
            params = CeleryParams.retry(process_type)

        assert params["queue"] == QueueNames.RETRY
        assert params.get("countdown") is None

    def test_db_save_and_send_notification_throws_exception_when_missing_template(self, sample_api_key, mocker):
        mocker.patch("app.celery.provider_tasks.deliver_sms.apply_async")
        assert Notification.query.count() == 0
        assert NotificationHistory.query.count() == 0

        notification = Notification(
            id=uuid.uuid4(),
            template_id=None,
            template_version=None,
            to="+16502532222",
            service=sample_api_key.service,
            personalisation=None,
            notification_type="sms",
            api_key_id=sample_api_key.id,
            key_type=sample_api_key.key_type,
            created_at=datetime.datetime(2016, 11, 11, 16, 8, 18),
        )

        with pytest.raises(SQLAlchemyError):
            db_save_and_send_notification(notification)

        assert Notification.query.count() == 0
        assert NotificationHistory.query.count() == 0

    def test_db_save_and_send_notification_does_not_increment_cache_if_test_key(
        self, notify_db, notify_db_session, sample_template, sample_job, mocker
    ):
        api_key = create_sample_api_key(
            notify_db=notify_db,
            notify_db_session=notify_db_session,
            service=sample_template.service,
            key_type="test",
        )
        mocker.patch("app.notifications.process_notifications.redis_store.get", return_value="cache")
        mocker.patch(
            "app.notifications.process_notifications.redis_store.get_all_from_hash",
            return_value="cache",
        )
        mocker.patch("app.celery.provider_tasks.deliver_sms.apply_async")
        daily_limit_cache = mocker.patch("app.notifications.process_notifications.redis_store.incr")
        template_usage_cache = mocker.patch("app.notifications.process_notifications.redis_store.increment_hash_value")

        assert Notification.query.count() == 0
        assert NotificationHistory.query.count() == 0

        notification = Notification(
            id=uuid.uuid4(),
            template_id=sample_template.id,
            template_version=sample_template.version,
            service=sample_template.service,
            personalisation={},
            notification_type="sms",
            api_key_id=api_key.id,
            key_type=api_key.key_type,
            job_id=sample_job.id,
            job_row_number=100,
            reference="ref",
            reply_to_text=sample_template.service.get_default_sms_sender(),
            to="+16502532222",
            created_at=datetime.datetime.utcnow(),
        )
        db_save_and_send_notification(notification)

        assert Notification.query.count() == 1

        assert not daily_limit_cache.called
        assert not template_usage_cache.called

    @freeze_time("2016-01-01 11:09:00.061258")
    def test_db_save_and_send_notification_doesnt_touch_cache_for_old_keys_that_dont_exist(
        self, sample_template, sample_api_key, mocker
    ):
        mock_incr = mocker.patch("app.notifications.process_notifications.redis_store.incr")
        mocker.patch("app.notifications.process_notifications.redis_store.get", return_value=None)
        mocker.patch(
            "app.notifications.process_notifications.redis_store.get_all_from_hash",
            return_value=None,
        )
        mocker.patch("app.celery.provider_tasks.deliver_sms.apply_async")
        notification = Notification(
            id=uuid.uuid4(),
            template_id=sample_template.id,
            template_version=sample_template.version,
            service=sample_template.service,
            personalisation={},
            notification_type="sms",
            api_key_id=sample_api_key.id,
            key_type=sample_api_key.key_type,
            reference="ref",
            to="+16502532222",
            created_at=datetime.datetime.utcnow(),
        )
        db_save_and_send_notification(notification)
        mock_incr.assert_not_called()

    @freeze_time("2016-01-01 11:09:00.061258")
    def test_db_save_and_send_notification_increments_cache_if_key_exists(self, sample_template, sample_api_key, mocker):
        mock_incr = mocker.patch("app.notifications.process_notifications.redis_store.incr")
        mocker.patch("app.notifications.process_notifications.redis_store.get", return_value=1)
        mocker.patch(
            "app.notifications.process_notifications.redis_store.get_all_from_hash",
            return_value={sample_template.id, 1},
        )
        mocker.patch("app.celery.provider_tasks.deliver_sms.apply_async")

        notification = Notification(
            id=uuid.uuid4(),
            template_id=sample_template.id,
            template_version=sample_template.version,
            service=sample_template.service,
            personalisation={},
            notification_type="sms",
            api_key_id=sample_api_key.id,
            key_type=sample_api_key.key_type,
            reference="ref2",
            to="+16502532222",
            created_at=datetime.datetime.utcnow(),
        )
        db_save_and_send_notification(notification)

        mock_incr.assert_called_once_with(
            str(sample_template.service_id) + "-2016-01-01-count",
        )
