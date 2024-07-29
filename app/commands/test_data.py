import functools
import math
import random
import uuid
from datetime import datetime

import click
from dateutil import rrule
from flask import cli as flask_cli

from app import db
from app.dao.services_dao import (
    dao_create_service,
    dao_fetch_all_services_by_user,
    delete_service_and_all_associated_db_objects,
)
from app.dao.templates_dao import dao_create_template
from app.dao.users_dao import (
    delete_model_user,
    delete_user_verify_codes,
    save_model_user,
)
from app.models import NotificationHistory, Organisation, Service, Template, User


@click.group(name="test-data", help="Generate and destroy test data")
def test_data_group():
    pass


class test_data_command:
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

        test_data_group.add_command(wrapper)

        return wrapper


def setup_test_data_commands(application):
    application.cli.add_command(test_data_group)


@test_data_command()
@click.option(
    "-p",
    "--prefix",
    default="notify-test-data",
    show_default=True,
    help="""
    test data prefix"
""",
)  # noqa
@click.option("-s", "--num_services", default=1, show_default=True, help="Number of services to create")
@click.option("-n", "--num_notifications", default=1, show_default=True, help="Number of notifications to create")
@click.option("-b", "--batch_size", default=10000, show_default=True, help="Number of notifications to create in each batch")
def generate(prefix, num_services, num_notifications, batch_size):
    """
    Generate test data
    """
    print("Building org...")
    org = Organisation(
        name=f"{prefix} {uuid.uuid4()}",
        organisation_type="central",
    )
    db.session.add(org)
    db.session.flush()
    print(" -> Done.")

    print(f"Building {num_services} services...")
    services = []
    templates = []

    for batch in range(num_services):
        data_prefix = f"{prefix}+{uuid.uuid4()}"
        user_email = f"{data_prefix}@cds-snc.ca"
        data = {
            "id": uuid.uuid4(),
            "name": user_email,
            "email_address": user_email,
            "password": f"{uuid.uuid4()}",
            "mobile_number": "16135550123",
            "state": "active",
            "blocked": False,
        }
        user = User(**data)
        save_model_user(user)

        service = Service(
            organisation_id=org.id,
            name=f"{data_prefix} service {batch}",
            created_by_id=user.id,
            active=True,
            restricted=False,
            organisation_type="central",
            message_limit=250_000,
            sms_daily_limit=10_000,
            email_from=f"{data_prefix}_{batch}@notify.works",
        )
        services.append(service)
        dao_create_service(service, user)

        service_templates = {
            "email": Template(
                name="{data_prefix}: email",
                service_id=service.id,
                template_type="email",
                subject="email",
                content="email body",
                created_by_id=user.id,
            ),
            "sms": Template(
                name="{data_prefix}: sms",
                service_id=service.id,
                template_type="sms",
                subject="sms",
                content="sms body",
                created_by_id=user.id,
            ),
        }
        dao_create_template(service_templates["email"])
        dao_create_template(service_templates["sms"])
        templates.append(service_templates)
        db.session.flush()
    print(" -> Done.")

    num_batches = math.ceil(num_notifications / batch_size)
    print(f"Building {num_notifications} notifications in batches of {batch_size}...")
    last_new_year = datetime(datetime.today().year - 1, 1, 1, 12, 0, 0)
    daily_dates_since_last_new_year = list(rrule.rrule(freq=rrule.DAILY, dtstart=last_new_year, until=datetime.today()))
    for batch in range(num_batches):
        print(f" -> Building batch #{batch + 1} of {num_batches}...")
        notifications_batch = []
        for _ in range(min(batch_size, num_notifications - (batch * batch_size))):
            notification_type = random.choice(["sms", "email"])
            service_index = random.choice(range(len(services)))
            service = services[service_index]
            template = templates[service_index][notification_type]
            notifications_batch.append(
                NotificationHistory(
                    id=uuid.uuid4(),
                    job_id=None,
                    job_row_number=None,
                    service_id=service.id,
                    template_id=template.id,
                    template_version=1,
                    api_key_id=None,
                    key_type="normal",
                    billable_units=1,
                    rate_multiplier=1,
                    notification_type=notification_type,
                    created_at=random.choice(daily_dates_since_last_new_year),
                    status="delivered",
                    client_reference=data_prefix,
                )
            )
        print(f"  -> Adding {len(notifications_batch)} notifications...")
        db.session.bulk_save_objects(notifications_batch)
        db.session.flush()
        print("  -> Done.")

    print("Committing...")
    db.session.commit()
    print("Finished.")


@test_data_command()
@click.option(
    "-p",
    "--prefix",
    default="notify-test-data",
    show_default=True,
    help="""
    test data prefix"
""",
)  # noqa
def delete(prefix):
    """
    Delete test data from the database
    """
    print(f"\n\nDeleting test data for prefix {prefix}...\n")
    users = User.query.filter(User.email_address.like("{}%".format(prefix))).all()
    org_ids = []
    if len(users) == 0:
        print("No users found with email prefix {}".format(prefix))
        return
    for usr in users:
        try:
            uuid.UUID(usr.email_address.split("@")[0].split("+")[1])
        except ValueError:
            print("Skipping {} as the user email doesn't contain a UUID.".format(usr.email_address))
        else:
            print(f"Deleting user {usr.email_address} and related data...")
            services = dao_fetch_all_services_by_user(usr.id)
            if services:
                for service in services:
                    org_ids.append(service.organisation_id)
                    delete_service_and_all_associated_db_objects(service)
            else:
                delete_user_verify_codes(usr)
                delete_model_user(usr)
            print(" -> Done.")

        db.session.commit()

    for org_id in set(org_ids):
        print(f"Deleting organisation {org_id}...")
        Organisation.query.filter_by(id=org_id).delete(synchronize_session=False)
    db.session.commit()

    print("Finished.")
