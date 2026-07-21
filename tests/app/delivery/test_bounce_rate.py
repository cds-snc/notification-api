from unittest.mock import ANY

from flask import current_app
from pytest_mock import MockFixture

from app.delivery import bounce_rate as bounce_rate_module
from app.models import EMAIL_TYPE, BounceRateStatus
from tests.conftest import set_config_values


class TestCheckServiceOverBounceRate:
    def test_critical_high_volume_suspends(self, mocker: MockFixture, notify_api, fake_uuid):
        with notify_api.app_context():
            mocker.patch("app.bounce_rate_client.check_bounce_rate_status", return_value=BounceRateStatus.CRITICAL.value)
            mocker.patch("app.bounce_rate_client.get_bounce_rate", return_value=current_app.config["BR_CRITICAL_PERCENTAGE"])
            mocker.patch("app.bounce_rate_client.get_total_notifications", return_value=1500)
            mocker.patch("app.delivery.bounce_rate.redis_store")
            bounce_rate_module.redis_store.set.return_value = True  # nx=True succeeds
            mock_remove_perm = mocker.patch("app.delivery.bounce_rate.dao_remove_service_permission")
            mock_send_task = mocker.patch("app.delivery.bounce_rate.notify_celery.send_task")
            mock_logger = mocker.patch("app.delivery.bounce_rate.current_app.logger.warning")

            bounce_rate_module.check_service_over_bounce_rate(fake_uuid)

            mock_remove_perm.assert_called_once_with(fake_uuid, EMAIL_TYPE)
            mock_send_task.assert_called_once_with(
                "send-bounce-rate-suspension-email",
                kwargs={"service_id": fake_uuid, "bounce_rate": current_app.config["BR_CRITICAL_PERCENTAGE"]},
                queue=ANY,
            )
            bounce_rate_module.redis_store.set.assert_called_once()
            mock_logger.assert_called_once()

    def test_critical_high_volume_already_sent(self, mocker: MockFixture, notify_api, fake_uuid):
        with notify_api.app_context():
            mocker.patch("app.bounce_rate_client.check_bounce_rate_status", return_value=BounceRateStatus.CRITICAL.value)
            mocker.patch("app.bounce_rate_client.get_bounce_rate", return_value=current_app.config["BR_CRITICAL_PERCENTAGE"])
            mocker.patch("app.bounce_rate_client.get_total_notifications", return_value=1500)
            mocker.patch("app.delivery.bounce_rate.redis_store")
            bounce_rate_module.redis_store.set.return_value = None  # nx=True fails (already set)
            mock_remove_perm = mocker.patch("app.delivery.bounce_rate.dao_remove_service_permission")
            mock_send_task = mocker.patch("app.delivery.bounce_rate.notify_celery.send_task")

            bounce_rate_module.check_service_over_bounce_rate(fake_uuid)

            mock_remove_perm.assert_not_called()
            mock_send_task.assert_not_called()

    def test_critical_low_volume_warns(self, mocker: MockFixture, notify_api, fake_uuid):
        with notify_api.app_context(), set_config_values(notify_api, {"BR_VOLUME_MINIMUM": 1000}):
            mocker.patch("app.bounce_rate_client.check_bounce_rate_status", return_value=BounceRateStatus.CRITICAL.value)
            mocker.patch("app.bounce_rate_client.get_bounce_rate", return_value=current_app.config["BR_CRITICAL_PERCENTAGE"])
            mocker.patch("app.bounce_rate_client.get_total_notifications", return_value=500)
            mocker.patch("app.delivery.bounce_rate.redis_store")
            bounce_rate_module.redis_store.set.return_value = True  # nx=True succeeds
            mock_remove_perm = mocker.patch("app.delivery.bounce_rate.dao_remove_service_permission")
            mock_send_task = mocker.patch("app.delivery.bounce_rate.notify_celery.send_task")
            mock_logger = mocker.patch("app.delivery.bounce_rate.current_app.logger.warning")

            bounce_rate_module.check_service_over_bounce_rate(fake_uuid)

            mock_remove_perm.assert_not_called()
            mock_send_task.assert_called_once_with(
                "send-bounce-rate-warning-email",
                kwargs={"service_id": fake_uuid, "bounce_rate": current_app.config["BR_CRITICAL_PERCENTAGE"]},
                queue=ANY,
            )
            bounce_rate_module.redis_store.set.assert_called_once()
            mock_logger.assert_called_once()

    def test_critical_low_volume_already_warned(self, mocker: MockFixture, notify_api, fake_uuid):
        with notify_api.app_context(), set_config_values(notify_api, {"BR_VOLUME_MINIMUM": 1000}):
            mocker.patch("app.bounce_rate_client.check_bounce_rate_status", return_value=BounceRateStatus.CRITICAL.value)
            mocker.patch("app.bounce_rate_client.get_bounce_rate", return_value=current_app.config["BR_CRITICAL_PERCENTAGE"])
            mocker.patch("app.bounce_rate_client.get_total_notifications", return_value=500)
            mocker.patch("app.delivery.bounce_rate.redis_store")
            bounce_rate_module.redis_store.set.return_value = None  # nx=True fails (already set)
            mock_send_task = mocker.patch("app.delivery.bounce_rate.notify_celery.send_task")

            bounce_rate_module.check_service_over_bounce_rate(fake_uuid)

            mock_send_task.assert_not_called()

    def test_warning_status_logs_only(self, mocker: MockFixture, notify_api, fake_uuid):
        with notify_api.app_context():
            mocker.patch("app.bounce_rate_client.check_bounce_rate_status", return_value=BounceRateStatus.WARNING.value)
            mocker.patch("app.bounce_rate_client.get_bounce_rate", return_value=current_app.config["BR_WARNING_PERCENTAGE"])
            mocker.patch("app.bounce_rate_client.get_total_notifications", return_value=5000)
            mock_logger = mocker.patch("app.delivery.bounce_rate.current_app.logger.warning")

            bounce_rate_module.check_service_over_bounce_rate(fake_uuid)

            mock_logger.assert_called_once_with(
                f"Service: {fake_uuid} has met or exceeded a warning bounce rate threshold of 5%. "
                f"Bounce rate: {current_app.config['BR_WARNING_PERCENTAGE']}"
            )

    def test_normal_status_no_action(self, mocker: MockFixture, notify_api, fake_uuid):
        with notify_api.app_context():
            mocker.patch("app.bounce_rate_client.check_bounce_rate_status", return_value=BounceRateStatus.NORMAL.value)
            mocker.patch("app.bounce_rate_client.get_bounce_rate", return_value=0.0)
            mocker.patch("app.bounce_rate_client.get_total_notifications", return_value=100)
            mock_logger = mocker.patch("app.delivery.bounce_rate.current_app.logger.warning")

            assert bounce_rate_module.check_service_over_bounce_rate(fake_uuid) is None
            mock_logger.assert_not_called()
