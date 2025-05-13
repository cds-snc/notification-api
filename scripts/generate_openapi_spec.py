#!/usr/bin/env python
"""
Script to generate OpenAPI specification for the Notification API.
"""

import json
import os
import sys
from pathlib import Path

# Add the parent directory to the path so we can import from the app
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from flask import Flask

from app.config import configs
from app.v2.notifications import v2_notification_blueprint
from app.v2.openapi.api import configure_api


def generate_openapi_spec():
    """Generate OpenAPI specification for the Notification API."""
    app = Flask(__name__)
    app.config.from_object(configs["development"])

    # Register the blueprint
    app.register_blueprint(v2_notification_blueprint)

    # Configure the API
    api = configure_api(v2_notification_blueprint)

    # Get the specification
    spec = api.__schema__

    # Save the specification to a file
    spec_dir = Path(__file__).parent / "openapi"
    spec_dir.mkdir(exist_ok=True)

    with open(spec_dir / "openapi.json", "w") as f:
        json.dump(spec, f, indent=2)

    print(f"OpenAPI specification saved to {spec_dir / 'openapi.json'}")


if __name__ == "__main__":
    generate_openapi_spec()
