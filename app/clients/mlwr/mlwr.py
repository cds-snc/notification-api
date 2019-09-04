from assemblyline_client import Client
from flask import current_app


def check_mlwr_score(sid):
    client = Client(
        current_app.config["MLWR_HOST"],
        apikey=(
            current_app.config["MLWR_USER"],
            current_app.config["MLWR_KEY"]))
    return client.submission(sid)
