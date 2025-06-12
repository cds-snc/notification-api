from io import BytesIO

from flask import send_file
from flask.views import MethodView
from flask_smorest import Page, abort

from app import api_user, authenticated_service
from app.dao import notifications_dao
from app.letters.utils import get_letter_pdf
from app.models import (
    LETTER_TYPE,
    NOTIFICATION_PENDING_VIRUS_CHECK,
    NOTIFICATION_TECHNICAL_FAILURE,
    NOTIFICATION_VIRUS_SCAN_FAILED,
)
from app.schema_validation import validate
from app.schemas import NotificationModelSchema, NotificationWithPersonalisationSchema
from app.v2.errors import BadRequestError, PDFNotReadyError
from app.v2.notifications import v2_notification_blueprint
from app.v2.notifications.notification_schemas import (
    GetNotificationsRequestBodySchema,
    UUIDSchema,
    notification_by_id,
)


@v2_notification_blueprint.route("/<notification_id>", tags=["Notifications"], methods=["GET"])
class GetNotificationById(MethodView):
    @v2_notification_blueprint.arguments(UUIDSchema, location="path", description="Notification ID")
    @v2_notification_blueprint.response(200, NotificationWithPersonalisationSchema)
    @v2_notification_blueprint.response(422, description="Invalid notification UUID format")
    def get(self, path_args, **kwargs):
        """Get a notification by its ID.

        Returns the notification details including personalisation data for
        the specified notification ID.
        """
        # TODO: Both Flask and flask-smorest pass request parameters, but we only want to use the path
        # args in this case as, in conjunction with the arg schema, it is "pre-validated".
        notification_id = path_args["notification_id"]
        notification = notifications_dao.get_notification_with_personalisation(
            authenticated_service.id, notification_id, key_type=None
        )
        if notification is None:
            abort(404, message="Notification not found in database")

        return notification


@v2_notification_blueprint.route("/<notification_id>/pdf", methods=["GET"])
def get_pdf_for_notification(notification_id):
    _data = {"notification_id": notification_id}
    validate(_data, notification_by_id)
    notification = notifications_dao.get_notification_by_id(notification_id, authenticated_service.id, _raise=True)

    if notification.notification_type != LETTER_TYPE:
        raise BadRequestError(message="Notification is not a letter")

    if notification.status == NOTIFICATION_VIRUS_SCAN_FAILED:
        raise BadRequestError(message="Document did not pass the virus scan")

    if notification.status == NOTIFICATION_TECHNICAL_FAILURE:
        raise BadRequestError(message="PDF not available for letters in status {}".format(notification.status))

    if notification.status == NOTIFICATION_PENDING_VIRUS_CHECK:
        raise PDFNotReadyError()

    try:
        pdf_data = get_letter_pdf(notification)
    except Exception:
        raise PDFNotReadyError()

    return send_file(path_or_file=BytesIO(pdf_data), mimetype="application/pdf")


class CursorPage(Page):
    """A custom page class for cursor-based pagination of notifications returned from
    an SQLAlchemy query.
    """

    @property
    def item_count(self):
        return self.collection.count()


@v2_notification_blueprint.route("", tags=["Notifications"], methods=["GET"])
class GetNotifications(MethodView):
    @v2_notification_blueprint.arguments(GetNotificationsRequestBodySchema, location="json")
    @v2_notification_blueprint.response(200, NotificationModelSchema(many=True))
    @v2_notification_blueprint.paginate(CursorPage)
    def get(self, args):
        """Get a list of notifications

        Returns a paginated list of notifications for the authenticated service.
        """
        paginated_notifications = notifications_dao.get_notifications_for_service(
            str(authenticated_service.id),
            filter_dict=args,
            key_type=api_user.key_type,
            personalisation=True,
            older_than=args.get("older_than"),
            client_reference=args.get("reference"),
            include_jobs=args.get("include_jobs"),
            should_page=False,  # We're letting smorest handle pagination
        )

        return paginated_notifications
