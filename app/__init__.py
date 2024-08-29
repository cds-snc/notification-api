import os
import random
import re
import string
import uuid
from time import monotonic
from typing import Any

from dotenv import load_dotenv
from flask import g, jsonify, make_response, request  # type: ignore
from flask_marshmallow import Marshmallow
from flask_migrate import Migrate
from flask_redis import FlaskRedis
from notifications_utils import logging, request_helper
from notifications_utils.clients.redis.bounce_rate import RedisBounceRate
from notifications_utils.clients.redis.redis_client import RedisClient
from notifications_utils.clients.statsd.statsd_client import StatsdClient
from notifications_utils.clients.zendesk.zendesk_client import ZendeskClient
from werkzeug.exceptions import HTTPException as WerkzeugHTTPException
from werkzeug.local import LocalProxy

from app.aws.metrics_logger import MetricsLogger
from app.celery.celery import NotifyCelery
from app.clients import Clients
from app.clients.document_download import DocumentDownloadClient
from app.clients.email.aws_ses import AwsSesClient
from app.clients.performance_platform.performance_platform_client import (
    PerformancePlatformClient,
)
from app.clients.salesforce.salesforce_client import SalesforceClient
from app.clients.sms.aws_pinpoint import AwsPinpointClient
from app.clients.sms.aws_sns import AwsSnsClient
from app.dbsetup import RoutingSQLAlchemy
from app.encryption import CryptoSigner
from app.json_provider import NotifyJSONProvider
from app.queue import RedisQueue

DATETIME_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
DATE_FORMAT = "%Y-%m-%d"

load_dotenv()

db: RoutingSQLAlchemy = RoutingSQLAlchemy()
migrate = Migrate()
marshmallow = Marshmallow()
notify_celery = NotifyCelery()
aws_ses_client = AwsSesClient()
aws_sns_client = AwsSnsClient()
aws_pinpoint_client = AwsPinpointClient()
signer_notification = CryptoSigner()
signer_personalisation = CryptoSigner()
signer_complaint = CryptoSigner()
signer_delivery_status = CryptoSigner()
signer_bearer_token = CryptoSigner()
signer_api_key = CryptoSigner()
signer_inbound_sms = CryptoSigner()
zendesk_client = ZendeskClient()
statsd_client = StatsdClient()
flask_redis = FlaskRedis()
flask_redis_publish = FlaskRedis(config_prefix="REDIS_PUBLISH")
redis_store = RedisClient()
bounce_rate_client = RedisBounceRate(redis_store)
metrics_logger = MetricsLogger()
# TODO: Rework instantiation to decouple redis_store.redis_store and pass it in.\
email_queue = RedisQueue("email")
sms_queue = RedisQueue("sms")
performance_platform_client = PerformancePlatformClient()
document_download_client = DocumentDownloadClient()
salesforce_client = SalesforceClient()

clients = Clients()

api_user: Any = LocalProxy(lambda: g.api_user)
authenticated_service: Any = LocalProxy(lambda: g.authenticated_service)

sms_bulk = RedisQueue("sms", process_type="bulk")
sms_normal = RedisQueue("sms", process_type="normal")
sms_priority = RedisQueue("sms", process_type="priority")
email_bulk = RedisQueue("email", process_type="bulk")
email_normal = RedisQueue("email", process_type="normal")
email_priority = RedisQueue("email", process_type="priority")

sms_bulk_publish = RedisQueue("sms", process_type="bulk")
sms_normal_publish = RedisQueue("sms", process_type="normal")
sms_priority_publish = RedisQueue("sms", process_type="priority")
email_bulk_publish = RedisQueue("email", process_type="bulk")
email_normal_publish = RedisQueue("email", process_type="normal")
email_priority_publish = RedisQueue("email", process_type="priority")


def create_app(application, config=None):
    from app.config import configs

    if config is None:
        notify_environment = os.getenv("NOTIFY_ENVIRONMENT", "development")
        config = configs[notify_environment]
        application.config.from_object(configs[notify_environment])
    else:
        application.config.from_object(config)

    application.config["NOTIFY_APP_NAME"] = application.name
    init_app(application)
    application.json = NotifyJSONProvider(application)
    request_helper.init_app(application)
    db.init_app(application)
    migrate.init_app(application, db=db)
    marshmallow.init_app(application)
    zendesk_client.init_app(application)
    statsd_client.init_app(application)
    logging.init_app(application, statsd_client)
    aws_sns_client.init_app(application, statsd_client=statsd_client)
    aws_pinpoint_client.init_app(application, statsd_client=statsd_client)
    aws_ses_client.init_app(application.config["AWS_REGION"], statsd_client=statsd_client)
    notify_celery.init_app(application)

    signer_notification.init_app(application, secret_key=application.config["SECRET_KEY"], salt="notification")
    signer_personalisation.init_app(application, secret_key=application.config["SECRET_KEY"], salt="personalisation")
    signer_complaint.init_app(application, secret_key=application.config["SECRET_KEY"], salt="complaint")
    signer_delivery_status.init_app(application, secret_key=application.config["SECRET_KEY"], salt="delivery_status")
    signer_bearer_token.init_app(application, secret_key=application.config["SECRET_KEY"], salt="bearer_token")
    signer_api_key.init_app(application, secret_key=application.config["SECRET_KEY"], salt="api_key")
    signer_inbound_sms.init_app(application, secret_key=application.config["SECRET_KEY"], salt="inbound_sms")

    performance_platform_client.init_app(application)
    document_download_client.init_app(application)
    clients.init_app(sms_clients=[aws_sns_client, aws_pinpoint_client], email_clients=[aws_ses_client])

    if application.config["FF_SALESFORCE_CONTACT"]:
        salesforce_client.init_app(application)

    flask_redis.init_app(application)
    flask_redis_publish.init_app(application)
    redis_store.init_app(application)
    bounce_rate_client.init_app(application)

    sms_bulk_publish.init_app(flask_redis_publish, metrics_logger)
    sms_normal_publish.init_app(flask_redis_publish, metrics_logger)
    sms_priority_publish.init_app(flask_redis_publish, metrics_logger)
    email_bulk_publish.init_app(flask_redis_publish, metrics_logger)
    email_normal_publish.init_app(flask_redis_publish, metrics_logger)
    email_priority_publish.init_app(flask_redis_publish, metrics_logger)

    sms_bulk.init_app(flask_redis, metrics_logger)
    sms_normal.init_app(flask_redis, metrics_logger)
    sms_priority.init_app(flask_redis, metrics_logger)
    email_bulk.init_app(flask_redis, metrics_logger)
    email_normal.init_app(flask_redis, metrics_logger)
    email_priority.init_app(flask_redis, metrics_logger)

    register_blueprint(application)
    register_v2_blueprints(application)

    # Log the application configuration
    application.logger.info(f"Notify config: {config.get_safe_config()}")

    # avoid circular imports by importing these files later
    from app.commands.bulk_db import setup_bulk_db_commands
    from app.commands.deprecated import setup_deprecated_commands
    from app.commands.support import setup_support_commands
    from app.commands.test_data import setup_test_data_commands

    setup_support_commands(application)
    setup_bulk_db_commands(application)
    setup_test_data_commands(application)
    setup_deprecated_commands(application)

    return application


def register_notify_blueprint(application, blueprint, auth_function, prefix=None):
    if not blueprint._got_registered_once:
        blueprint.before_request(auth_function)
        if prefix:
            application.register_blueprint(blueprint, url_prefix=prefix)
        else:
            application.register_blueprint(blueprint)


def register_blueprint(application):
    from app.accept_invite.rest import accept_invite
    from app.api_key.rest import api_key_blueprint, sre_tools_blueprint
    from app.authentication.auth import (
        requires_admin_auth,
        requires_auth,
        requires_cache_clear_auth,
        requires_no_auth,
        requires_sre_auth,
    )
    from app.billing.rest import billing_blueprint
    from app.cache.rest import cache_blueprint
    from app.complaint.complaint_rest import complaint_blueprint
    from app.email_branding.rest import email_branding_blueprint
    from app.events.rest import events as events_blueprint
    from app.inbound_number.rest import inbound_number_blueprint
    from app.inbound_sms.rest import inbound_sms as inbound_sms_blueprint
    from app.invite.rest import invite as invite_blueprint
    from app.job.rest import job_blueprint
    from app.letter_branding.letter_branding_rest import letter_branding_blueprint
    from app.letters.rest import letter_job
    from app.notifications.notifications_letter_callback import (
        letter_callback_blueprint,
    )
    from app.notifications.rest import notifications as notifications_blueprint
    from app.organisation.invite_rest import organisation_invite_blueprint
    from app.organisation.rest import organisation_blueprint
    from app.platform_stats.rest import platform_stats_blueprint
    from app.provider_details.rest import provider_details as provider_details_blueprint
    from app.service.callback_rest import service_callback_blueprint
    from app.service.rest import service_blueprint
    from app.status.healthcheck import status as status_blueprint
    from app.template.rest import template_blueprint
    from app.template.template_category_rest import template_category_blueprint
    from app.template_folder.rest import template_folder_blueprint
    from app.template_statistics.rest import (
        template_statistics as template_statistics_blueprint,
    )
    from app.user.rest import user_blueprint

    register_notify_blueprint(application, service_blueprint, requires_admin_auth, "/service")

    register_notify_blueprint(application, user_blueprint, requires_admin_auth, "/user")

    register_notify_blueprint(application, template_blueprint, requires_admin_auth)

    register_notify_blueprint(application, status_blueprint, requires_no_auth)

    register_notify_blueprint(application, notifications_blueprint, requires_auth)

    register_notify_blueprint(application, job_blueprint, requires_admin_auth)

    register_notify_blueprint(application, invite_blueprint, requires_admin_auth)

    register_notify_blueprint(application, inbound_number_blueprint, requires_admin_auth)

    register_notify_blueprint(application, inbound_sms_blueprint, requires_admin_auth)

    register_notify_blueprint(application, accept_invite, requires_admin_auth, "/invite")

    register_notify_blueprint(application, template_statistics_blueprint, requires_admin_auth)

    register_notify_blueprint(application, events_blueprint, requires_admin_auth)

    register_notify_blueprint(application, provider_details_blueprint, requires_admin_auth, "/provider-details")

    register_notify_blueprint(application, email_branding_blueprint, requires_admin_auth, "/email-branding")

    register_notify_blueprint(application, api_key_blueprint, requires_admin_auth, "/api-key")

    register_notify_blueprint(application, sre_tools_blueprint, requires_sre_auth, "/sre-tools")

    register_notify_blueprint(application, letter_job, requires_admin_auth)

    register_notify_blueprint(application, letter_callback_blueprint, requires_no_auth)

    register_notify_blueprint(application, billing_blueprint, requires_admin_auth)

    register_notify_blueprint(application, service_callback_blueprint, requires_admin_auth)

    register_notify_blueprint(application, organisation_blueprint, requires_admin_auth, "/organisations")

    register_notify_blueprint(application, organisation_invite_blueprint, requires_admin_auth)

    register_notify_blueprint(application, complaint_blueprint, requires_admin_auth)

    register_notify_blueprint(application, platform_stats_blueprint, requires_admin_auth, "/platform-stats")

    register_notify_blueprint(application, template_folder_blueprint, requires_admin_auth)

    register_notify_blueprint(application, letter_branding_blueprint, requires_admin_auth)

    register_notify_blueprint(application, template_category_blueprint, requires_admin_auth)

    register_notify_blueprint(application, cache_blueprint, requires_cache_clear_auth)

def register_v2_blueprints(application):
    from app.authentication.auth import requires_auth
    from app.v2.inbound_sms.get_inbound_sms import (
        v2_inbound_sms_blueprint as get_inbound_sms,
    )
    from app.v2.notifications import (  # noqa
        get_notifications,
        post_notifications,
        v2_notification_blueprint,
    )
    from app.v2.template import (  # noqa
        get_template,
        post_template,
        v2_template_blueprint,
    )
    from app.v2.templates.get_templates import v2_templates_blueprint as get_templates

    register_notify_blueprint(application, v2_notification_blueprint, requires_auth)

    register_notify_blueprint(application, get_templates, requires_auth)

    register_notify_blueprint(application, v2_template_blueprint, requires_auth)

    register_notify_blueprint(application, get_inbound_sms, requires_auth)


def init_app(app):
    @app.before_request
    def record_user_agent():
        statsd_client.incr("user-agent.{}".format(process_user_agent(request.headers.get("User-Agent", None))))

    @app.before_request
    def record_request_details():
        g.start = monotonic()
        g.endpoint = request.endpoint

    @app.after_request
    def after_request(response):
        response.headers.add("Access-Control-Allow-Origin", "*")
        response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
        response.headers.add("Access-Control-Allow-Methods", "GET,PUT,POST,DELETE")
        return response

    @app.errorhandler(Exception)
    def exception(error):
        app.logger.exception(error)
        # error.code is set for our exception types.
        msg = getattr(error, "message", str(error))
        code = getattr(error, "code", 500)
        return jsonify(result="error", message=msg), code

    @app.errorhandler(WerkzeugHTTPException)
    def werkzeug_exception(e):
        return make_response(jsonify(result="error", message=e.description), e.code, e.get_headers())

    @app.errorhandler(404)
    def page_not_found(e):
        msg = e.description or "Not found"
        return jsonify(result="error", message=msg), 404


def create_uuid():
    return str(uuid.uuid4())


def create_random_identifier():
    return "".join(random.choice(string.ascii_uppercase + string.digits) for _ in range(16))


def process_user_agent(user_agent_string):
    if user_agent_string is None:
        return "unknown"

    m = re.search(
        r"^(?P<name>notify.*)/(?P<version>\d+.\d+.\d+)$",
        user_agent_string,
        re.IGNORECASE,
    )
    if m:
        return f'{m.group("name").lower()}.{m.group("version").replace(".", "-")}'
    return "non-notify-user-agent"
