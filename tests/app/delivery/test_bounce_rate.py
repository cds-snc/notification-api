from unittest.mock import ANY

from flask import current_app
from pytest_mock import MockFixture

from app.delivery import bounce_rate as bounce_rate_module
from app.models import EMAIL_TYPE
from tests.conftest import set_config_values


class TestCheckServiceOverBounceRate:
    def test_critical_high_volume_suspends(self, mocker: MockFixture, notify_api, fake_uuid):
        """>=1000 messages, bounce rate >=10% → suspend sending"""
        with notify_api.app_context():
            mocker.patch("app.bounce_rate_client.check_bounce_rate_status", return_value="critical")
            mocker.patch("app.bounce_rate_client.get_bounce_rate", return_value=current_app.config["BR_CRITICAL_PERCENTAGE"])
            mocker.patch("app.bounce_rate_client.get_total_notifications", return_value=1500)
            mock_set_suspension_key = mocker.patch("app.bounce_rate_client.set_suspension_email_key", return_value=True)
            mock_set_warning_key = mocker.patch("app.bounce_rate_client.set_warning_email_key", return_value=True)
            mock_remove_perm = mocker.patch("app.delivery.bounce_rate.dao_remove_service_permission")
            mock_send_task = mocker.patch("app.delivery.bounce_rate.notify_celery.send_task")

            bounce_rate_module.check_service_over_bounce_rate(fake_uuid)

            mock_remove_perm.assert_called_once_with(fake_uuid, EMAIL_TYPE)
            mock_send_task.assert_called_once_with(
                "send-bounce-rate-suspension-email",
                kwargs={"service_id": fake_uuid, "bounce_rate": current_app.config["BR_CRITICAL_PERCENTAGE"]},
                queue=ANY,
            )
            mock_set_suspension_key.assert_called_once_with(fake_uuid, bounce_rate_module.TWENTY_FOUR_HOURS_IN_SECONDS)
            # Warning key should also be set to prevent a follow-up warning email
            mock_set_warning_key.assert_called_once_with(fake_uuid, bounce_rate_module.TWENTY_FOUR_HOURS_IN_SECONDS)

    def test_critical_high_volume_already_sent(self, mocker: MockFixture, notify_api, fake_uuid):
        """>=1000 messages, bounce rate >=10%, but suspension email already sent → no duplicate"""
        with notify_api.app_context():
            mocker.patch("app.bounce_rate_client.check_bounce_rate_status", return_value="critical")
            mocker.patch("app.bounce_rate_client.get_bounce_rate", return_value=current_app.config["BR_CRITICAL_PERCENTAGE"])
            mocker.patch("app.bounce_rate_client.get_total_notifications", return_value=1500)
            mocker.patch("app.bounce_rate_client.set_suspension_email_key", return_value=None)  # nx=True fails
            mock_set_warning_key = mocker.patch("app.bounce_rate_client.set_warning_email_key")
            mock_remove_perm = mocker.patch("app.delivery.bounce_rate.dao_remove_service_permission")
            mock_send_task = mocker.patch("app.delivery.bounce_rate.notify_celery.send_task")

            bounce_rate_module.check_service_over_bounce_rate(fake_uuid)

            mock_remove_perm.assert_not_called()
            mock_send_task.assert_not_called()
            mock_set_warning_key.assert_not_called()

    def test_warning_high_volume_sends_warning_email(self, mocker: MockFixture, notify_api, fake_uuid):
        """>=1000 messages, bounce rate >=5% <10% → warning email"""
        with notify_api.app_context():
            mocker.patch("app.bounce_rate_client.check_bounce_rate_status", return_value="warning")
            mocker.patch("app.bounce_rate_client.get_bounce_rate", return_value=current_app.config["BR_WARNING_PERCENTAGE"])
            mocker.patch("app.bounce_rate_client.get_total_notifications", return_value=1500)
            mocker.patch("app.bounce_rate_client.set_warning_email_key", return_value=True)
            mock_remove_perm = mocker.patch("app.delivery.bounce_rate.dao_remove_service_permission")
            mock_send_task = mocker.patch("app.delivery.bounce_rate.notify_celery.send_task")

            bounce_rate_module.check_service_over_bounce_rate(fake_uuid)

            mock_remove_perm.assert_not_called()
            mock_send_task.assert_called_once_with(
                "send-bounce-rate-warning-email",
                kwargs={"service_id": fake_uuid, "bounce_rate": current_app.config["BR_WARNING_PERCENTAGE"]},
                queue=ANY,
            )

    def test_warning_high_volume_already_warned(self, mocker: MockFixture, notify_api, fake_uuid):
        """>=1000 messages, bounce rate >=5% <10%, but warning already sent → no duplicate"""
        with notify_api.app_context():
            mocker.patch("app.bounce_rate_client.check_bounce_rate_status", return_value="warning")
            mocker.patch("app.bounce_rate_client.get_bounce_rate", return_value=current_app.config["BR_WARNING_PERCENTAGE"])
            mocker.patch("app.bounce_rate_client.get_total_notifications", return_value=1500)
            mocker.patch("app.bounce_rate_client.set_warning_email_key", return_value=None)  # nx=True fails
            mock_send_task = mocker.patch("app.delivery.bounce_rate.notify_celery.send_task")

            bounce_rate_module.check_service_over_bounce_rate(fake_uuid)

            mock_send_task.assert_not_called()

    def test_low_volume_no_action(self, mocker: MockFixture, notify_api, fake_uuid):
        """<1000 messages → no email sent regardless of bounce rate"""
        with notify_api.app_context(), set_config_values(notify_api, {"BR_VOLUME_MINIMUM": 1000}):
            mocker.patch("app.bounce_rate_client.check_bounce_rate_status", return_value="critical")
            mocker.patch("app.bounce_rate_client.get_bounce_rate", return_value=0.87)
            mocker.patch("app.bounce_rate_client.get_total_notifications", return_value=100)
            mock_remove_perm = mocker.patch("app.delivery.bounce_rate.dao_remove_service_permission")
            mock_send_task = mocker.patch("app.delivery.bounce_rate.notify_celery.send_task")

            bounce_rate_module.check_service_over_bounce_rate(fake_uuid)

            mock_remove_perm.assert_not_called()
            mock_send_task.assert_not_called()

    def test_normal_bounce_rate_no_action(self, mocker: MockFixture, notify_api, fake_uuid):
        """>=1000 messages but bounce rate <5% → no action"""
        with notify_api.app_context():
            mocker.patch("app.bounce_rate_client.check_bounce_rate_status", return_value="normal")
            mocker.patch("app.bounce_rate_client.get_bounce_rate", return_value=0.02)
            mocker.patch("app.bounce_rate_client.get_total_notifications", return_value=5000)
            mock_send_task = mocker.patch("app.delivery.bounce_rate.notify_celery.send_task")

            bounce_rate_module.check_service_over_bounce_rate(fake_uuid)

            mock_send_task.assert_not_called()
