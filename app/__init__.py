import os
import random
import string
import uuid
from dotenv import load_dotenv

from flask import _request_ctx_stack, request, g, jsonify, make_response
from flask_sqlalchemy import SQLAlchemy as _SQLAlchemy
from flask_marshmallow import Marshmallow
from flask_migrate import Migrate
from time import monotonic
from notifications_utils.clients.zendesk.zendesk_client import ZendeskClient
from notifications_utils.clients.statsd.statsd_client import StatsdClient
from notifications_utils.clients.redis.redis_client import RedisClient
from notifications_utils import logging, request_helper
from werkzeug.exceptions import HTTPException as WerkzeugHTTPException
from werkzeug.local import LocalProxy

from app.celery.celery import NotifyCelery
from app.clients import Clients
from app.clients.document_download import DocumentDownloadClient
from app.clients.email.aws_ses import AwsSesClient
from app.clients.email.sendgrid_client import SendGridClient
from app.clients.sms.firetext import FiretextClient
from app.clients.sms.loadtesting import LoadtestingClient
from app.clients.sms.mmg import MMGClient
from app.clients.sms.aws_sns import AwsSnsClient
from app.clients.sms.aws_pinpoint import AwsPinpointClient
from app.clients.sms.twilio import TwilioSMSClient
from app.clients.performance_platform.performance_platform_client import PerformancePlatformClient
from app.encryption import Encryption

DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
DATE_FORMAT = "%Y-%m-%d"

load_dotenv()


class SQLAlchemy(_SQLAlchemy):
    """We need to subclass SQLAlchemy in order to override create_engine options"""

    def apply_driver_hacks(self, app, info, options):
        super().apply_driver_hacks(app, info, options)
        if 'connect_args' not in options:
            options['connect_args'] = {}
        options['connect_args']["options"] = "-c statement_timeout={}".format(
            int(app.config['SQLALCHEMY_STATEMENT_TIMEOUT']) * 1000
        )


db = SQLAlchemy()
migrate = Migrate()
ma = Marshmallow()
notify_celery = NotifyCelery()
firetext_client = FiretextClient()
loadtest_client = LoadtestingClient()
mmg_client = MMGClient()
aws_ses_client = AwsSesClient()
send_grid_client = SendGridClient()
aws_sns_client = AwsSnsClient()
aws_pinpoint_client = AwsPinpointClient()
twilio_sms_client = TwilioSMSClient(
    account_sid=os.getenv('TWILIO_ACCOUNT_SID'),
    auth_token=os.getenv('TWILIO_AUTH_TOKEN'),
    from_number=os.getenv('TWILIO_FROM_NUMBER'),
)
encryption = Encryption()
zendesk_client = ZendeskClient()
statsd_client = StatsdClient()
redis_store = RedisClient()
performance_platform_client = PerformancePlatformClient()
document_download_client = DocumentDownloadClient()

clients = Clients()

api_user = LocalProxy(lambda: _request_ctx_stack.top.api_user)
authenticated_service = LocalProxy(lambda: _request_ctx_stack.top.authenticated_service)


def create_app(application):
    from app.config import configs

    notify_environment = os.getenv('NOTIFY_ENVIRONMENT', 'development')

    application.config.from_object(configs[notify_environment])

    application.config['NOTIFY_APP_NAME'] = application.name
    init_app(application)
    request_helper.init_app(application)
    db.init_app(application)
    migrate.init_app(application, db=db)
    ma.init_app(application)
    zendesk_client.init_app(application)
    statsd_client.init_app(application)
    logging.init_app(application, statsd_client)
    firetext_client.init_app(application, statsd_client=statsd_client)
    loadtest_client.init_app(application, statsd_client=statsd_client)
    mmg_client.init_app(application, statsd_client=statsd_client)
    aws_sns_client.init_app(application, statsd_client=statsd_client)
    aws_pinpoint_client.init_app(application, statsd_client=statsd_client)
    aws_ses_client.init_app(application.config['AWS_REGION'], statsd_client=statsd_client)
    send_grid_client.init_app(application.config['SENDGRID_API_KEY'], statsd_client=statsd_client)
    twilio_sms_client.init_app(
        logger=application.logger,
        callback_notify_url_host=application.config["API_HOST_NAME"]
    )
    notify_celery.init_app(application)
    encryption.init_app(application)
    redis_store.init_app(application)
    performance_platform_client.init_app(application)
    document_download_client.init_app(application)
    clients.init_app(
        sms_clients=[
            firetext_client,
            mmg_client,
            aws_sns_client,
            aws_pinpoint_client,
            loadtest_client,
            twilio_sms_client,
        ],
        email_clients=[aws_ses_client, send_grid_client]
    )

    register_blueprint(application)
    register_v2_blueprints(application)

    # avoid circular imports by importing this file later
    from app.commands import setup_commands
    setup_commands(application)

    return application


def register_blueprint(application):
    from app.service.rest import service_blueprint
    from app.service.callback_rest import service_callback_blueprint
    from app.user.rest import user_blueprint
    from app.template.rest import template_blueprint
    from app.status.healthcheck import status as status_blueprint
    from app.job.rest import job_blueprint
    from app.notifications.rest import notifications as notifications_blueprint
    from app.invite.rest import invite as invite_blueprint
    from app.accept_invite.rest import accept_invite
    from app.template_statistics.rest import template_statistics as template_statistics_blueprint
    from app.events.rest import events as events_blueprint
    from app.provider_details.rest import provider_details as provider_details_blueprint
    from app.email_branding.rest import email_branding_blueprint
    from app.api_key.rest import api_key_blueprint
    from app.inbound_number.rest import inbound_number_blueprint
    from app.inbound_sms.rest import inbound_sms as inbound_sms_blueprint
    from app.notifications.receive_notifications import receive_notifications_blueprint
    from app.celery.process_ses_receipts_tasks import ses_callback_blueprint, ses_smtp_callback_blueprint
    from app.notifications.notifications_sms_callback import sms_callback_blueprint
    from app.notifications.notifications_letter_callback import letter_callback_blueprint
    from app.notifications.notifications_email_callback import email_callback_blueprint
    from app.authentication.auth import requires_admin_auth, requires_auth, requires_no_auth
    from app.letters.rest import letter_job
    from app.billing.rest import billing_blueprint
    from app.organisation.rest import organisation_blueprint
    from app.organisation.invite_rest import organisation_invite_blueprint
    from app.complaint.complaint_rest import complaint_blueprint
    from app.platform_stats.rest import platform_stats_blueprint
    from app.template_folder.rest import template_folder_blueprint
    from app.letter_branding.letter_branding_rest import letter_branding_blueprint

    service_blueprint.before_request(requires_admin_auth)
    application.register_blueprint(service_blueprint, url_prefix='/service')

    user_blueprint.before_request(requires_admin_auth)
    application.register_blueprint(user_blueprint, url_prefix='/user')

    template_blueprint.before_request(requires_admin_auth)
    application.register_blueprint(template_blueprint)

    status_blueprint.before_request(requires_no_auth)
    application.register_blueprint(status_blueprint)

    # delivery receipts
    ses_callback_blueprint.before_request(requires_no_auth)
    application.register_blueprint(ses_callback_blueprint)

    ses_smtp_callback_blueprint.before_request(requires_no_auth)
    application.register_blueprint(ses_smtp_callback_blueprint)

    # TODO: make sure research mode can still trigger sms callbacks, then re-enable this
    sms_callback_blueprint.before_request(requires_no_auth)
    application.register_blueprint(sms_callback_blueprint)

    email_callback_blueprint.before_request(requires_no_auth)
    application.register_blueprint(email_callback_blueprint)

    # inbound sms
    receive_notifications_blueprint.before_request(requires_no_auth)
    application.register_blueprint(receive_notifications_blueprint)

    notifications_blueprint.before_request(requires_auth)
    application.register_blueprint(notifications_blueprint)

    job_blueprint.before_request(requires_admin_auth)
    application.register_blueprint(job_blueprint)

    invite_blueprint.before_request(requires_admin_auth)
    application.register_blueprint(invite_blueprint)

    inbound_number_blueprint.before_request(requires_admin_auth)
    application.register_blueprint(inbound_number_blueprint)

    inbound_sms_blueprint.before_request(requires_admin_auth)
    application.register_blueprint(inbound_sms_blueprint)

    accept_invite.before_request(requires_admin_auth)
    application.register_blueprint(accept_invite, url_prefix='/invite')

    template_statistics_blueprint.before_request(requires_admin_auth)
    application.register_blueprint(template_statistics_blueprint)

    events_blueprint.before_request(requires_admin_auth)
    application.register_blueprint(events_blueprint)

    provider_details_blueprint.before_request(requires_admin_auth)
    application.register_blueprint(provider_details_blueprint, url_prefix='/provider-details')

    email_branding_blueprint.before_request(requires_admin_auth)
    application.register_blueprint(email_branding_blueprint, url_prefix='/email-branding')

    api_key_blueprint.before_request(requires_admin_auth)
    application.register_blueprint(api_key_blueprint, url_prefix='/api-key')

    letter_job.before_request(requires_admin_auth)
    application.register_blueprint(letter_job)

    letter_callback_blueprint.before_request(requires_no_auth)
    application.register_blueprint(letter_callback_blueprint)

    billing_blueprint.before_request(requires_admin_auth)
    application.register_blueprint(billing_blueprint)

    service_callback_blueprint.before_request(requires_admin_auth)
    application.register_blueprint(service_callback_blueprint)

    organisation_blueprint.before_request(requires_admin_auth)
    application.register_blueprint(organisation_blueprint, url_prefix='/organisations')

    organisation_invite_blueprint.before_request(requires_admin_auth)
    application.register_blueprint(organisation_invite_blueprint)

    complaint_blueprint.before_request(requires_admin_auth)
    application.register_blueprint(complaint_blueprint)

    platform_stats_blueprint.before_request(requires_admin_auth)
    application.register_blueprint(platform_stats_blueprint, url_prefix='/platform-stats')

    template_folder_blueprint.before_request(requires_admin_auth)
    application.register_blueprint(template_folder_blueprint)

    letter_branding_blueprint.before_request(requires_admin_auth)
    application.register_blueprint(letter_branding_blueprint)


def register_v2_blueprints(application):
    from app.v2.inbound_sms.get_inbound_sms import v2_inbound_sms_blueprint as get_inbound_sms
    from app.v2.notifications.post_notifications import v2_notification_blueprint as post_notifications
    from app.v2.notifications.get_notifications import v2_notification_blueprint as get_notifications
    from app.v2.template.get_template import v2_template_blueprint as get_template
    from app.v2.templates.get_templates import v2_templates_blueprint as get_templates
    from app.v2.template.post_template import v2_template_blueprint as post_template
    from app.authentication.auth import requires_auth

    post_notifications.before_request(requires_auth)
    application.register_blueprint(post_notifications)

    get_notifications.before_request(requires_auth)
    application.register_blueprint(get_notifications)

    get_templates.before_request(requires_auth)
    application.register_blueprint(get_templates)

    get_template.before_request(requires_auth)
    application.register_blueprint(get_template)

    post_template.before_request(requires_auth)
    application.register_blueprint(post_template)

    get_inbound_sms.before_request(requires_auth)
    application.register_blueprint(get_inbound_sms)


def init_app(app):
    @app.before_request
    def record_user_agent():
        statsd_client.incr("user-agent.{}".format(process_user_agent(request.headers.get('User-Agent', None))))

    @app.before_request
    def record_request_details():
        g.start = monotonic()
        g.endpoint = request.endpoint

    @app.after_request
    def after_request(response):
        response.headers.add('Access-Control-Allow-Origin', '*')
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
        response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE')
        return response

    @app.errorhandler(Exception)
    def exception(error):
        app.logger.exception(error)
        # error.code is set for our exception types.
        msg = getattr(error, 'message', str(error))
        code = getattr(error, 'code', 500)
        return jsonify(result='error', message=msg), code

    @app.errorhandler(WerkzeugHTTPException)
    def werkzeug_exception(e):
        return make_response(
            jsonify(result='error', message=e.description),
            e.code,
            e.get_headers()
        )

    @app.errorhandler(404)
    def page_not_found(e):
        msg = e.description or "Not found"
        return jsonify(result='error', message=msg), 404


def create_uuid():
    return str(uuid.uuid4())


def create_random_identifier():
    return ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(16))


def process_user_agent(user_agent_string):
    if user_agent_string and user_agent_string.lower().startswith("notify"):
        components = user_agent_string.split("/")
        client_name = components[0].lower()
        client_version = components[1].replace(".", "-")
        return "{}.{}".format(client_name, client_version)
    elif user_agent_string and not user_agent_string.lower().startswith("notify"):
        return "non-notify-user-agent"
    else:
        return "unknown"
