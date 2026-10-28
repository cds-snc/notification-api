from app.models import Notification, ScheduledNotification
from tests.app.db import (
    create_notification,
    create_scheduled_one_off_notification,
    create_service,
    create_template,
    save_scheduled_notification,
)


class TestGetScheduledNotificationsForService:
    def test_returns_scheduled_notifications_ordered_by_scheduled_for(self, admin_request, sample_template):
        later = create_scheduled_one_off_notification(sample_template, scheduled_for="2099-05-13 15:15")
        sooner = create_scheduled_one_off_notification(sample_template, scheduled_for="2099-05-12 15:15")
        other_template = create_template(service=create_service(service_name="other"))
        create_scheduled_one_off_notification(other_template, scheduled_for="2099-05-12 15:15")

        response = admin_request.get(
            "service.get_scheduled_notifications_for_service",
            service_id=sample_template.service_id,
        )

        assert response["total"] == 2
        assert [n["id"] for n in response["notifications"]] == [str(sooner.notification_id), str(later.notification_id)]
        assert response["notifications"][0]["scheduled_for"] == "2099-05-12T15:15:00.000000+00:00"
        assert response["notifications"][0]["template"]["name"] == sample_template.name
        assert response["notifications"][0]["to"] == sooner.to
        assert response["notifications"][0]["notification_type"] == "sms"
        assert response["notifications"][0]["status"] == "created"
        # Serializing doesn't add anything to the notifications table
        assert Notification.query.count() == 0

    def test_paginates(self, admin_request, sample_template):
        for day in range(10, 13):
            create_scheduled_one_off_notification(sample_template, scheduled_for=f"2099-05-{day} 15:15")

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


class TestGetScheduledNotification:
    def test_get_notification_returns_scheduled_notification(self, admin_request, sample_template_with_placeholders):
        scheduled_notification = create_scheduled_one_off_notification(
            sample_template_with_placeholders,
            scheduled_for="2099-05-12 15:15",
            personalisation={"name": "Jo"},
            client_reference="my-ref",
            billable_units=1,
        )

        response = admin_request.get(
            "service.get_notification_for_service",
            service_id=scheduled_notification.service_id,
            notification_id=scheduled_notification.notification_id,
        )

        assert response["id"] == str(scheduled_notification.notification_id)
        assert response["scheduled_for"] == "2099-05-12T15:15:00.000000+00:00"
        assert response["status"] == "created"
        assert response["to"] == scheduled_notification.to
        assert response["personalisation"] == {"name": "Jo"}
        assert response["client_reference"] == "my-ref"
        assert response["billable_units"] == 1
        assert response["template"]["id"] == str(sample_template_with_placeholders.id)
        assert response["template"]["content"] == sample_template_with_placeholders.content
        assert response["job"] is None
        assert response["created_by"] is None
        assert Notification.query.count() == 0

    def test_get_notification_doesnt_return_another_services_scheduled_notification(self, admin_request, sample_template):
        scheduled_notification = create_scheduled_one_off_notification(sample_template)

        admin_request.get(
            "service.get_notification_for_service",
            service_id=create_service(service_name="other").id,
            notification_id=scheduled_notification.notification_id,
            _expected_status=404,
        )

    def test_get_notification_scheduled_for_is_none_when_not_scheduled(self, admin_request, sample_notification):
        response = admin_request.get(
            "service.get_notification_for_service",
            service_id=sample_notification.service_id,
            notification_id=sample_notification.id,
        )

        assert response["scheduled_for"] is None

    def test_get_notification_includes_scheduled_for_when_legacy_scheduled_notification_is_pending(
        self, admin_request, sample_template
    ):
        notification = save_scheduled_notification(
            create_notification(template=sample_template), scheduled_for="2099-05-12 15:15"
        )

        response = admin_request.get(
            "service.get_notification_for_service",
            service_id=notification.service_id,
            notification_id=notification.id,
        )

        assert response["scheduled_for"] == "2099-05-12T15:15:00.000000+00:00"


class TestCancelScheduledNotificationForService:
    def test_cancels_scheduled_notification(self, admin_request, sample_template):
        scheduled_notification = create_scheduled_one_off_notification(sample_template)

        response = admin_request.post(
            "service.cancel_scheduled_notification_for_service",
            service_id=scheduled_notification.service_id,
            notification_id=scheduled_notification.notification_id,
        )

        assert response == {"result": "success"}
        assert ScheduledNotification.query.count() == 0

    def test_cancels_legacy_scheduled_notification(self, admin_request, sample_template):
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
        scheduled_notification = create_scheduled_one_off_notification(sample_template)
        other_service = create_service(service_name="other")

        admin_request.post(
            "service.cancel_scheduled_notification_for_service",
            service_id=other_service.id,
            notification_id=scheduled_notification.notification_id,
            _expected_status=404,
        )

        assert ScheduledNotification.query.count() == 1

    def test_returns_400_when_notification_is_not_scheduled(self, admin_request, sample_notification):
        # Includes scheduled notifications that have been sent, they're only in the notifications table once sent
        response = admin_request.post(
            "service.cancel_scheduled_notification_for_service",
            service_id=sample_notification.service_id,
            notification_id=sample_notification.id,
            _expected_status=400,
        )

        assert response["message"] == "Notification is not scheduled and cannot be cancelled"
        assert Notification.query.get(sample_notification.id) is not None

    def test_returns_400_when_legacy_scheduled_notification_already_sent(self, admin_request, sample_template):
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
