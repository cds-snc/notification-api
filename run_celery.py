#!/usr/bin/env python
from flask import Flask
from dotenv import load_dotenv
import newrelic.agent  # See https://bit.ly/2xBVKBH
newrelic.agent.initialize()  # noqa: E402

# notify_celery is referenced from manifest_delivery_base.yml, and cannot be removed
from app import notify_celery, create_app  # noqa

load_dotenv()

application = Flask('delivery')
create_app(application)
application.app_context().push()
