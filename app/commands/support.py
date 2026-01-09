import functools
from typing import Union
from uuid import UUID

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
from app.dao.users_dao import (
    dao_archive_user,
    get_archived_email_address,
    get_user_by_email,
    get_user_by_id,
    user_can_be_archived,
)
from app.models import Notification, User


@click.group(name="support", help="Support commands")
def support_group():
    pass


class support_command:
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

        support_group.add_command(wrapper)

        return wrapper


def setup_support_commands(application):
    application.cli.add_command(support_group)


@support_command(name="admin")
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


@support_command(name="list-routes")
def list_routes():
    """List URLs of all application routes."""
    for rule in sorted(current_app.url_map.iter_rules(), key=lambda r: r.rule):
        print("{:10} {}".format(", ".join(rule.methods - set(["OPTIONS", "HEAD"])), rule.rule))


@support_command(name="replay-service-callbacks")
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
        send_delivery_status_to_service.apply_async([str(n.id), signed_status_update, service_id], queue=QueueNames.CALLBACKS)

    print(
        "Replay service status for service: {}. Sent {} notification status updates to the queue".format(
            service_id, len(notifications)
        )
    )


@support_command(name="archive-user")
@click.option("--user-email", required=False, help="User email address to archive")
@click.option("--user-id", required=False, help="User ID to archive")
@click.option("--dry-run", is_flag=True, default=False, help="Validate without archiving")
def archive_user(user_email: str | None = None, user_id: str | None = None, dry_run: bool = False):
    """
    Archive a GC Notify user account.

    This command will:

    1. Validate the user exists and is not already archived
    2. Check the user has no active services or other team members can manage settings
    3. Archive the user (unless --dry-run is specified)

    Args:
        user_email (str): The email address of the user to archive. Mutually exclusive with user_id.
        user_id (str): The UUID of the user to archive. Mutually exclusive with user_email.
        dry_run (bool): If True, perform validation only without actually archiving the user.

    Returns:
        None

    Side Effects:
        - Prints status messages to stdout
        - Prompts for confirmation before archiving (unless dry_run is True)
        - Modifies the user's email address to prevent login
        - Removes the user from all services and organisations
        - Sets user state to 'inactive'
        - Commits changes to the database

    Raises:
        NoResultFound: If the user cannot be found (caught and printed as error)
        Exception: Any database errors during archival (caught, rolled back, and printed as error)
        InvalidRequest: User cannot be removed from service if associated services does not have another team member who can manage settings
    """
    # Validate mutually exclusive arguments
    if user_email and user_id:
        print("Error: Cannot specify both --user-email and --user-id. Please provide only one.")
        return

    if not user_email and not user_id:
        print("Error: Must specify either --user-email or --user-id")
        return

    identifier = user_email if user_email else UUID(user_id)
    user = _fetch_user(identifier)

    # Check if already archived
    if user.email_address.startswith("_archived_"):
        print(f"Error: User {user.email_address} is already archived")
        return

    # Validate user can be archived
    if not user_can_be_archived(user):
        print("Error: User cannot be archived.")
        print("User may be the only team member with 'manage settings' permission for one or more services.")
        print("Please ensure all services have at least one other active team member with 'manage settings' permission.")
        return

    # Show what will be archived
    active_services = [s for s in user.services if s.active]
    if active_services:
        print(f"\nUser is associated with {len(active_services)} active service(s):")
        for service in active_services:
            print(f"  - {service.name} (ID: {service.id})")
    else:
        print("\nUser has no active services")

    if dry_run:
        print("\n[DRY RUN] Validation passed. User can be archived.")
        print(f"[DRY RUN] Email would be changed to: {get_archived_email_address(user.email_address)}")
        print("[DRY RUN] User would be removed from all services and organisations")
        print("[DRY RUN] User state would be set to 'inactive'")
        return

    # Confirm archival
    print(f"\nWARNING: You are about to archive user '{user.name}' ({user.email_address})")
    print("This action will:")
    print("  - Remove the user from all services and organisations")
    print("  - Set user state to 'inactive'")
    print("  - Modify the email address to prevent login")
    print("  - Sign the user out of all sessions")

    confirmation = input("\nType 'archive' to confirm: ")
    if confirmation != "archive":
        print("Archival cancelled")
        return

    # Archive user
    dao_archive_user(user)
    print(f"\nSuccess: User '{user.name}' has been archived")
    print(f"New email address: {user.email_address}")


def _fetch_user(identifier: str | UUID) -> User:
    """Fetch and display user information by email or ID.
    Args:
        user_email: The email address of the user to fetch. Defaults to None.
        user_id: The ID of the user to fetch. Defaults to None.
    Returns:
        None. Prints user information if found, or an error message if not found
        or if an exception occurs.
    Raises:
        ValueError: If neither user_email nor user_id is provided
        NoResultFound: If the user cannot be found (caught and printed as error)
        Exception: Any database errors during fetch (caught and printed as error)
    """
    try:
        if isinstance(identifier, str):
            user = get_user_by_email(identifier)
            print(f"Found user: {user.name} (ID: {user.id}, Email: {user.email_address})")
        elif isinstance(identifier, UUID):
            user = get_user_by_id(identifier)
            print(f"Found user: {user.name} (ID: {user.id}, Email: {user.email_address})")
        else:
            print("Error: identifier must be either user_email (str) or user_id (UUID)")
            raise ValueError("Invalid identifier type")
        return user
    except NoResultFound as e:
        raise NoResultFound(f"User not found: {identifier}") from e
    except Exception as e:
        raise Exception(f"Error finding user {identifier}") from e
