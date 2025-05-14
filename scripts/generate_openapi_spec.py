#!/usr/bin/env python
"""
Script to generate OpenAPI specification for the Notification API.
"""

import json
import os
import sys
from pathlib import Path

import yaml

# Add the parent directory to the path so we can import from the app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from flask import Flask

from app.config import configs
from app.v2.notifications import v2_notification_blueprint


def generate_openapi_spec():
    """Generate OpenAPI specification for the Notification API."""
    app = Flask(__name__)
    app.config.from_object(configs["development"])

    # Set SERVER_NAME to build URLs outside of request context
    app.config["SERVER_NAME"] = "localhost"
    app.config["PREFERRED_URL_SCHEME"] = "http"
    app.config["APPLICATION_ROOT"] = "/"

    # Register the blueprint
    app.register_blueprint(v2_notification_blueprint)

    # The API is already configured in the blueprint's __init__.py
    # So we just access the api attribute of the blueprint
    from app.v2.notifications import api

    # We need to use the application context to get the schema
    with app.app_context():
        # Get the specification
        spec = api.__schema__

        # Save the specification to files
        spec_dir = Path(__file__).parent / "openapi"
        spec_dir.mkdir(exist_ok=True)

        # Save as JSON for backward compatibility
        with open(spec_dir / "openapi.json", "w") as f:
            json.dump(spec, f, indent=2)

        # Save as YAML
        with open(spec_dir / "openapi.yaml", "w") as f:
            yaml.dump(spec, f, sort_keys=False, default_flow_style=False)

        print("OpenAPI specification saved to:")
        print(f"  - JSON: {spec_dir / 'openapi.json'}")
        print(f"  - YAML: {spec_dir / 'openapi.yaml'}")


if __name__ == "__main__":
    generate_openapi_spec()
