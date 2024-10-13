#!/usr/bin/env python
# flake8: noqa
from __future__ import print_function

import os
import time

# Check if profiling should be enabled
enable_profiling = os.getenv('NOTIFY_PROFILE') is not None

if enable_profiling:
    print("Profiling enabled")
    import cProfile
    import pstats
    from pstats import SortKey

    # Create a cProfile.Profile object
    profiler = cProfile.Profile()
    # Start profiling
    profiler.enable()

# Timer start for initialization.
start_time = time.time()

import newrelic.agent  # See https://bit.ly/2xBVKBH
from apig_wsgi import make_lambda_handler
from aws_xray_sdk.core import patch_all, xray_recorder
from aws_xray_sdk.ext.flask.middleware import XRayMiddleware
from dotenv import load_dotenv
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from app import create_app
from app.aws.xray.context import NotifyContext

# Patch all supported libraries for X-Ray
# Used to trace requests and responses through the stack
patch_all()

load_dotenv()

application = Flask("api")
application.wsgi_app = ProxyFix(application.wsgi_app)  # type: ignore

app = create_app(application)

xray_recorder.configure(service='Notify-API', context=NotifyContext())
XRayMiddleware(app, xray_recorder)

apig_wsgi_handler = make_lambda_handler(app, binary_support=True)

if os.environ.get("USE_LOCAL_JINJA_TEMPLATES") == "True":
    print("")
    print("========================================================")
    print("")
    print("WARNING: USING LOCAL JINJA from /jinja_templates FOLDER!")
    print(".env USE_LOCAL_JINJA_TEMPLATES=True")
    print("")
    print("========================================================")
    print("")

# Timer end for initialization.
end_time = time.time()
elapsed_time = end_time - start_time
print(f"Elapsed time: {elapsed_time:.2f}s")

if enable_profiling:
    # Stop profiling
    profiler.disable()
    # Dump profiling results to a file
    profiler.dump_stats('profile_results.prof')
    # Analyze profiling results
    with open('profile_report.txt', 'w') as f:
        stats = pstats.Stats('profile_results.prof', stream=f)
        stats.sort_stats(SortKey.CUMULATIVE)
        stats.print_stats()


def handler(event, context):
    newrelic.agent.initialize()  # noqa: E402
    newrelic.agent.register_application(timeout=20.0)
    return apig_wsgi_handler(event, context)
