#!/usr/bin/env python
from __future__ import print_function

import os
import time

# Check if profiling should be enabled
enable_profiling = os.getenv("NOTIFY_PROFILE") is not None

if enable_profiling:
    print("Application profiling enabled")
    import atexit
    import cProfile
    from datetime import datetime
    import pstats
    from pstats import SortKey

    # Create a cProfile.Profile object
    profiler = cProfile.Profile()
    # Start profiling
    profiler.enable()

    def close_profiling():
        # Timer end for initialization.
        end_time = time.time()
        elapsed_time = end_time - start_time
        print(f"Elapsed time: {elapsed_time:.2f}s")

        # Stop profiling
        profiler.disable()

        filestamp = datetime.now().strftime("%Y%m%d-%H%M")

        # Dump profiling results to a file
        profiler.dump_stats(f"profile_results-app-nr811-{filestamp}.prof")
        # Analyze profiling results
        with open(f"profile_report-app-nr811-{filestamp}.txt", "w") as f:
            stats = pstats.Stats(f"profile_results-app-nr811-{filestamp}.prof", stream=f)
            stats.sort_stats(SortKey.CUMULATIVE)
            stats.print_stats()

    atexit.register(close_profiling)


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

# xray_recorder.configure(service="Notify-API", context=NotifyContext())
# XRayMiddleware(app, xray_recorder)

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


def handler(event, context):
    newrelic.agent.initialize(environment=app.config["NOTIFY_ENVIRONMENT"])  # noqa: E402
    newrelic.agent.register_application(timeout=20.0)
    return apig_wsgi_handler(event, context)
