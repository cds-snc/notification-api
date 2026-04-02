#!/usr/bin/env python

from dotenv import load_dotenv
from environs import Env
from flask import Flask

env = Env()
ff_enable_otel = env.bool("FF_ENABLE_OTEL", default=False)

# notify_celery is referenced from manifest_delivery_base.yml, and cannot be removed
from app import create_app, notify_celery  # noqa
from app.otel_celery_metrics import init_otel_celery_metrics

load_dotenv()

application = Flask("celery")
create_app(application)
if application.config.get("OTEL_REQUEST_METRICS_ENABLED", False):
    init_otel_celery_metrics(application)

if not ff_enable_otel:
    from aws_xray_sdk.core import xray_recorder
    from aws_xray_sdk.ext.flask.middleware import XRayMiddleware

    from app.aws.xray.context import NotifyContext

    xray_recorder.configure(service="Notify", context=NotifyContext())
    XRayMiddleware(application, xray_recorder)

application.app_context().push()
