import functools

import click
from flask import cli as flask_cli
from flask import current_app
from sqlalchemy.orm.exc import NoResultFound

from app import DATETIME_FORMAT, db, signer_delivery_status
from app.celery.service_callback_tasks import send_delivery_status_to_service
from app.config import QueueNames
from app.dao.service_callback_api_dao import (
    get_service_delivery_status_callback_api_for_service,
)
from app.models import Notification, User


@click.group(name="command", help="Additional commands")
def command_group():
    pass


class notify_command:
    def __init__(self, name=None):
        self.name = name

    def __call__(self, func):
        # we need to call the flask with_appcontext decorator to ensure the config is loaded, db connected etc etc.
        # we also need to use functools.wraps to carry through the names and docstrings etc of the functions.
        # Then we need to turn it into a click.Command - that's what command_group.add_command expects.
        @click.command(name=self.name)
        @functools.wraps(func)
        @flask_cli.with_appcontext
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)

        command_group.add_command(wrapper)

        return wrapper


def setup_commands(application):
    application.cli.add_command(command_group)


@notify_command(name="admin")
@click.option("-u", "--user_email", required=True, help="user email address")
@click.option("--on/--off", required=False, default=True, show_default="on", help="set admin on or off")
def toggle_admin(user_email, on):
    """
    Set a user to be a platform admin or not
    """
    try:
        user = User.query.filter(User.email_address == user_email).one()
    except NoResultFound:
        print(f"User {user_email} not found")
        return
    user.platform_admin = on
    db.session.commit()
    print(f"User {user.email_address} is now {'an admin' if user.platform_admin else 'not an admin'}")


@notify_command(name="list-routes")
def list_routes():
    """List URLs of all application routes."""
    for rule in sorted(current_app.url_map.iter_rules(), key=lambda r: r.rule):
        print("{:10} {}".format(", ".join(rule.methods - set(["OPTIONS", "HEAD"])), rule.rule))


@notify_command(name="replay-service-callbacks")
@click.option(
    "-f",
    "--file_name",
    required=True,
    help="""Full path of the file to upload, file is a contains client references of
              notifications that need the status to be sent to the service.""",
)
@click.option(
    "-s",
    "--service_id",
    required=True,
    help="""The service that the callbacks are for""",
)
def replay_service_callbacks(file_name, service_id):
    print("Start send service callbacks for service: ", service_id)
    callback_api = get_service_delivery_status_callback_api_for_service(service_id=service_id)
    if not callback_api:
        print("Callback api was not found for service: {}".format(service_id))
        return

    errors = []
    notifications = []
    file = open(file_name)

    for ref in file:
        try:
            notification = Notification.query.filter_by(client_reference=ref.strip()).one()
            notifications.append(notification)
        except NoResultFound:
            errors.append("Reference: {} was not found in notifications.".format(ref))

    for e in errors:
        print(e)
    if errors:
        raise Exception("Some notifications for the given references were not found")

    for n in notifications:
        data = {
            "notification_id": str(n.id),
            "notification_client_reference": n.client_reference,
            "notification_to": n.to,
            "notification_status": n.status,
            "notification_created_at": n.created_at.strftime(DATETIME_FORMAT),
            "notification_updated_at": n.updated_at.strftime(DATETIME_FORMAT),
            "notification_sent_at": n.sent_at.strftime(DATETIME_FORMAT),
            "notification_type": n.notification_type,
            "service_callback_api_url": callback_api.url,
            "service_callback_api_bearer_token": callback_api.bearer_token,
        }
        signed_status_update = signer_delivery_status.sign(data)
        send_delivery_status_to_service.apply_async([str(n.id), signed_status_update], queue=QueueNames.CALLBACKS)

    print(
        "Replay service status for service: {}. Sent {} notification status updates to the queue".format(
            service_id, len(notifications)
        )
    )
