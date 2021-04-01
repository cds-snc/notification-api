from app import process_user_agent

import pytest


@pytest.mark.parametrize(
    "input, expected",
    [
        (
            "Mozilla/5.0 (iPad; U; CPU like Mac OS X; en-us) AppleWebKit/531.21.10 (KHTML, like Gecko) Mobile/7B405",
            "non-notify-user-agent",
        ),
        ("NOTIFY-API-PYTHON-CLIENT/3.0.0", "notify-api-python-client.3-0-0"),
        (None, "unknown"),
        ("NotifyApiKeyClient", "non-notify-user-agent"),
        ("nearlyNOTIFY-API-PYTHON-CLIENT/3.0.0", "non-notify-user-agent"),
        ("NOTIFY-API-PYTHON-CLIENT/3.0.0almost", "non-notify-user-agent"),
    ],
)
def test_process_user_agent(input, expected):
    assert expected == process_user_agent(input)
