#!/usr/bin/env python
import os

import newrelic.agent  # See https://bit.ly/2xBVKBH
from dotenv import load_dotenv
from flask import Flask

environment = os.environ.get("NOTIFY_ENVIRONMENT")
newrelic.agent.initialize(environment=environment)  # noqa: E402

# notify_celery is referenced from manifest_delivery_base.yml, and cannot be removed
from app import create_app, notify_celery  # noqa

load_dotenv()

application = Flask("celery")
create_app(application)

application.app_context().push()
