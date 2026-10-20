from app.models import Notification, ScheduledNotification
from tests.app.db import (
    create_notification,
    create_service,
    create_template,
    save_notification,
    save_scheduled_notification,
)


class TestGetScheduledNotificationsForService:
    def test_returns_pending_scheduled_notifications_ordered_by_scheduled_for(self, admin_request, sample_template):
        later = save_scheduled_notification(create_notification(template=sample_template), scheduled_for="2099-05-13 15:15")
        sooner = save_scheduled_notification(create_notification(template=sample_template), scheduled_for="2099-05-12 15:15")
        # already sent / not scheduled / other service
        save_scheduled_notification(create_notification(template=sample_template, status="sending"), "2017-05-12 15:15")
        save_notification(create_notification(template=sample_template))
        other_template = create_template(service=create_service(service_name="other"))
        save_scheduled_notification(create_notification(template=other_template), scheduled_for="2099-05-12 15:15")

        response = admin_request.get(
            "service.get_scheduled_notifications_for_service",
            service_id=sample_template.service_id,
        )

        assert response["total"] == 2
        assert [n["id"] for n in response["notifications"]] == [str(sooner.id), str(later.id)]
        assert response["notifications"][0]["scheduled_for"] == "2099-05-12T15:15:00.000000+00:00"
        assert response["notifications"][0]["template"]["name"] == sample_template.name

    def test_paginates(self, admin_request, sample_template):
        for day in range(10, 13):
            save_scheduled_notification(create_notification(template=sample_template), scheduled_for=f"2099-05-{day} 15:15")

        response = admin_request.get(
            "service.get_scheduled_notifications_for_service",
            service_id=sample_template.service_id,
            page_size=2,
        )

        assert response["total"] == 3
        assert response["page_size"] == 2
        assert len(response["notifications"]) == 2

    def test_rejects_invalid_page_size(self, admin_request, sample_template):
        admin_request.get(
            "service.get_scheduled_notifications_for_service",
            service_id=sample_template.service_id,
            page_size=0,
            _expected_status=400,
        )


class TestScheduledForOnNotification:
    def test_get_notification_includes_scheduled_for_when_pending(self, admin_request, sample_template):
        notification = save_scheduled_notification(
            create_notification(template=sample_template), scheduled_for="2099-05-12 15:15"
        )

        response = admin_request.get(
            "service.get_notification_for_service",
            service_id=notification.service_id,
            notification_id=notification.id,
        )

        assert response["scheduled_for"] == "2099-05-12T15:15:00.000000+00:00"

    def test_get_notification_scheduled_for_is_none_when_not_pending(self, admin_request, sample_template):
        notification = save_scheduled_notification(
            create_notification(template=sample_template, status="sending"), scheduled_for="2017-05-12 15:15"
        )

        response = admin_request.get(
            "service.get_notification_for_service",
            service_id=notification.service_id,
            notification_id=notification.id,
        )

        assert response["scheduled_for"] is None

    def test_get_notification_scheduled_for_is_none_when_not_scheduled(self, admin_request, sample_notification):
        response = admin_request.get(
            "service.get_notification_for_service",
            service_id=sample_notification.service_id,
            notification_id=sample_notification.id,
        )

        assert response["scheduled_for"] is None


class TestPendingScheduledNotificationsHiddenFromSentLists:
    def test_get_all_notifications_excludes_pending_scheduled_by_default(self, admin_request, sample_template):
        sent = save_notification(create_notification(template=sample_template))
        save_scheduled_notification(create_notification(template=sample_template), scheduled_for="2099-05-12 15:15")

        response = admin_request.get(
            "service.get_all_notifications_for_service",
            service_id=sample_template.service_id,
        )

        assert [n["id"] for n in response["notifications"]] == [str(sent.id)]

    def test_get_all_notifications_can_include_pending_scheduled(self, admin_request, sample_template):
        save_notification(create_notification(template=sample_template))
        save_scheduled_notification(create_notification(template=sample_template), scheduled_for="2099-05-12 15:15")

        response = admin_request.get(
            "service.get_all_notifications_for_service",
            service_id=sample_template.service_id,
            include_scheduled=True,
        )

        assert len(response["notifications"]) == 2

    def test_search_by_recipient_excludes_pending_scheduled(self, admin_request, sample_template):
        sent = save_notification(
            create_notification(template=sample_template, to_field="6502532222", normalised_to="16502532222")
        )
        save_scheduled_notification(
            create_notification(template=sample_template, to_field="6502532222", normalised_to="16502532222"),
            scheduled_for="2099-05-12 15:15",
        )

        response = admin_request.get(
            "service.get_all_notifications_for_service",
            service_id=sample_template.service_id,
            to="6502532222",
            template_type="sms",
        )

        assert [n["id"] for n in response["notifications"]] == [str(sent.id)]


class TestCancelScheduledNotificationForService:
    def test_cancels_pending_scheduled_notification(self, admin_request, sample_template):
        notification = save_scheduled_notification(
            create_notification(template=sample_template), scheduled_for="2099-05-12 15:15"
        )

        response = admin_request.post(
            "service.cancel_scheduled_notification_for_service",
            service_id=notification.service_id,
            notification_id=notification.id,
        )

        assert response == {"result": "success"}
        assert Notification.query.get(notification.id) is None
        assert ScheduledNotification.query.filter_by(notification_id=notification.id).first() is None

    def test_returns_404_when_notification_not_found(self, admin_request, sample_service, fake_uuid):
        response = admin_request.post(
            "service.cancel_scheduled_notification_for_service",
            service_id=sample_service.id,
            notification_id=fake_uuid,
            _expected_status=404,
        )

        assert response["message"] == "Notification not found"

    def test_returns_404_when_notification_belongs_to_another_service(self, admin_request, sample_template):
        notification = save_scheduled_notification(
            create_notification(template=sample_template), scheduled_for="2099-05-12 15:15"
        )
        other_service = create_service(service_name="other")

        admin_request.post(
            "service.cancel_scheduled_notification_for_service",
            service_id=other_service.id,
            notification_id=notification.id,
            _expected_status=404,
        )

        assert Notification.query.get(notification.id) is not None

    def test_returns_400_when_notification_is_not_scheduled(self, admin_request, sample_notification):
        response = admin_request.post(
            "service.cancel_scheduled_notification_for_service",
            service_id=sample_notification.service_id,
            notification_id=sample_notification.id,
            _expected_status=400,
        )

        assert response["message"] == "Notification is not scheduled and cannot be cancelled"
        assert Notification.query.get(sample_notification.id) is not None

    def test_returns_400_when_scheduled_notification_already_sent(self, admin_request, sample_template):
        notification = save_scheduled_notification(
            create_notification(template=sample_template, status="sending"), scheduled_for="2017-05-12 15:15"
        )

        response = admin_request.post(
            "service.cancel_scheduled_notification_for_service",
            service_id=notification.service_id,
            notification_id=notification.id,
            _expected_status=400,
        )

        assert response["message"] == "Notification has already been sent and cannot be cancelled"
        assert Notification.query.get(notification.id) is not None
