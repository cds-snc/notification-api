import functools
import itertools
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import click
from click_datetime import Datetime as click_dt
from flask import cli as flask_cli
from flask import current_app, json
from notifications_utils.statsd_decorators import statsd
from sqlalchemy.exc import IntegrityError

from app import db
from app.dao.annual_billing_dao import dao_create_or_update_annual_billing_for_year
from app.dao.organisation_dao import (
    dao_add_service_to_organisation,
    dao_get_organisation_by_email_address,
)
from app.dao.provider_rates_dao import (
    create_provider_rates as dao_create_provider_rates,
)
from app.dao.services_dao import dao_fetch_service_by_id
from app.models import (
    PROVIDERS,
    Domain,
    EmailBranding,
    LetterBranding,
    Organisation,
    Service,
    User,
)


@click.group(name="bulk-db", help="Bulk updates to the database")
def bulk_db_group():
    pass


class bulk_db_command:
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

        bulk_db_group.add_command(wrapper)

        return wrapper


def setup_bulk_db_commands(application):
    application.cli.add_command(bulk_db_group)


@bulk_db_command()
@click.option("-p", "--provider_name", required=True, type=click.Choice(PROVIDERS))
@click.option(
    "-c",
    "--cost",
    required=True,
    help="Cost (pence) per message including decimals",
    type=float,
)
@click.option("-d", "--valid_from", required=True, type=click_dt(format="%Y-%m-%dT%H:%M:%S"))
def create_provider_rates(provider_name, cost, valid_from):
    """
    Backfill rates for a given provider
    """
    cost = Decimal(cost)
    dao_create_provider_rates(provider_name, valid_from, cost)


@bulk_db_command(name="populate-annual-billing")
@click.option(
    "-y",
    "--year",
    required=True,
    type=int,
    help="""The year to populate the annual billing data for, i.e. 2019""",
)
def populate_annual_billing(year):
    """
    add annual_billing for given year.
    """
    sql = """
        Select id from services where active = true
        except
        select service_id
        from annual_billing
        where financial_year_start = :year
    """
    services_without_annual_billing = db.session.execute(sql, {"year": year})
    for row in services_without_annual_billing:
        latest_annual_billing = """
            Select free_sms_fragment_limit
            from annual_billing
            where service_id = :service_id
            order by financial_year_start desc limit 1
        """
        free_allowance_rows = db.session.execute(latest_annual_billing, {"service_id": row.id})
        free_allowance = [x[0] for x in free_allowance_rows]
        print("create free limit of {} for service: {}".format(free_allowance[0], row.id))
        dao_create_or_update_annual_billing_for_year(
            service_id=row.id,
            free_sms_fragment_limit=free_allowance[0],
            financial_year_start=int(year),
        )


@bulk_db_command(name="insert-inbound-numbers")
@click.option(
    "-f",
    "--file_name",
    required=True,
    help="""Full path of the file to upload, file is a contains inbound numbers,
              one number per line. The number must have the format of 07... not 447....""",
)
def insert_inbound_numbers_from_file(file_name):
    print("Inserting inbound numbers from {}".format(file_name))
    file = open(file_name)
    sql = "insert into inbound_numbers values('{}', '{}', 'mmg', null, True, now(), null);"

    for line in file:
        print(line)
        db.session.execute(sql.format(uuid.uuid4(), line.strip()))
        db.session.commit()
    file.close()


@bulk_db_command(name="bulk-invite-user-to-service")
@click.option(
    "-f",
    "--file_name",
    required=True,
    help="Full path of the file containing a list of email address for people to invite to a service",
)
@click.option(
    "-s",
    "--service_id",
    required=True,
    help="The id of the service that the invite is for",
)
@click.option("-u", "--user_id", required=True, help="The id of the user that the invite is from")
@click.option(
    "-a",
    "--auth_type",
    required=False,
    help="The authentication type for the user, sms_auth or email_auth. Defaults to sms_auth if not provided",
)
@click.option("-p", "--permissions", required=True, help="Comma separated list of permissions.")
def bulk_invite_user_to_service(file_name, service_id, user_id, auth_type, permissions):
    #  permissions
    #  manage_users | manage_templates | manage_settings
    #  send messages ==> send_texts | send_emails | send_letters
    #  Access API keys manage_api_keys
    #  platform_admin
    #  view_activity
    # "send_texts,send_emails,send_letters,view_activity"
    from app.invite.rest import create_invited_user

    file = open(file_name)
    for email_address in file:
        data = {
            "service": service_id,
            "email_address": email_address.strip(),
            "from_user": user_id,
            "permissions": permissions,
            "auth_type": auth_type,
            "invite_link_host": current_app.config["ADMIN_BASE_URL"],
        }
        with current_app.test_request_context(
            path="/service/{}/invite/".format(service_id),
            method="POST",
            data=json.dumps(data),
            headers={"Content-Type": "application/json"},
        ):
            try:
                response = create_invited_user(service_id)
                if response[1] != 201:
                    print("*** ERROR occurred for email address: {}".format(email_address.strip()))
                print(response[0].get_data(as_text=True))
            except Exception as e:
                print("*** ERROR occurred for email address: {}. \n{}".format(email_address.strip(), e))

    file.close()


@bulk_db_command(name="archive-jobs-created-between-dates")
@click.option(
    "-s",
    "--start_date",
    required=True,
    help="start date inclusive",
    type=click_dt(format="%Y-%m-%d"),
)
@click.option(
    "-e",
    "--end_date",
    required=True,
    help="end date inclusive",
    type=click_dt(format="%Y-%m-%d"),
)
@statsd(namespace="tasks")
def update_jobs_archived_flag(start_date, end_date):
    current_app.logger.info("Archiving jobs created between {} to {}".format(start_date, end_date))

    process_date = start_date
    total_updated = 0

    while process_date < end_date:
        start_time = datetime.utcnow()
        sql = """update
                    jobs set archived = true
                where
                    created_at >= (date :start + time '00:00:00') at time zone 'America/Toronto'
                    at time zone 'UTC'
                    and created_at < (date :end + time '00:00:00') at time zone 'America/Toronto' at time zone 'UTC'"""

        result = db.session.execute(sql, {"start": process_date, "end": process_date + timedelta(days=1)})
        db.session.commit()
        current_app.logger.info(
            "jobs: --- Completed took {}ms. Archived {} jobs for {}".format(
                datetime.now() - start_time, result.rowcount, process_date
            )
        )

        process_date += timedelta(days=1)

        total_updated += result.rowcount
    current_app.logger.info("Total archived jobs = {}".format(total_updated))


@bulk_db_command(name="populate-organisations-from-file")
@click.option(
    "-f",
    "--file_name",
    required=True,
    help="Pipe delimited file containing organisation name, sector, crown, argeement_signed, domains",
)
def populate_organisations_from_file(file_name):
    # [0] organisation name:: name of the organisation insert if organisation is missing.
    # [1] sector:: Central | Local | NHS only
    # [2] crown:: TRUE | FALSE only
    # [3] argeement_signed:: TRUE | FALSE
    # [4] domains:: comma separated list of domains related to the organisation
    # [5] email branding name: name of the default email branding for the org
    # [6] letter branding name: name of the default letter branding for the org

    # The expectation is that the organisation, organisation_to_service
    # and user_to_organisation will be cleared before running this command.
    # Ignoring duplicates allows us to run the command again with the same file or same file with new rows.
    with open(file_name, "r") as f:

        def boolean_or_none(field):
            if field == "1":
                return True
            elif field == "0":
                return False
            else:
                return None

        for line in itertools.islice(f, 1, None):
            columns = line.split("|")
            print(columns)
            email_branding = None
            email_branding_column = columns[5].strip()
            if len(email_branding_column) > 0:
                email_branding = EmailBranding.query.filter(EmailBranding.name == email_branding_column).one()
            letter_branding = None
            letter_branding_column = columns[6].strip()
            if len(letter_branding_column) > 0:
                letter_branding = LetterBranding.query.filter(LetterBranding.name == letter_branding_column).one()
            data = {
                "name": columns[0],
                "active": True,
                "agreement_signed": boolean_or_none(columns[3]),
                "crown": boolean_or_none(columns[2]),
                "organisation_type": columns[1].lower(),
                "email_branding_id": email_branding.id if email_branding else None,
                "letter_branding_id": letter_branding.id if letter_branding else None,
            }
            org = Organisation(**data)
            try:
                db.session.add(org)
                db.session.commit()
            except IntegrityError:
                print("duplicate org", org.name)
                db.session.rollback()
            domains = columns[4].split(",")
            for d in domains:
                if len(d.strip()) > 0:
                    domain = Domain(domain=d.strip(), organisation_id=org.id)
                    try:
                        db.session.add(domain)
                        db.session.commit()
                    except IntegrityError:
                        print("duplicate domain", d.strip())
                        db.session.rollback()


@bulk_db_command(name="associate-services-to-organisations")
def associate_services_to_organisations():
    services = Service.get_history_model().query.filter_by(version=1).all()

    for s in services:
        created_by_user = User.query.filter_by(id=s.created_by_id).first()
        organisation = dao_get_organisation_by_email_address(created_by_user.email_address)
        service = dao_fetch_service_by_id(service_id=s.id)
        if organisation:
            dao_add_service_to_organisation(service=service, organisation_id=organisation.id)

    print("finished associating services to organisations")
