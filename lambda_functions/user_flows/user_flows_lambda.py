import pytest


def user_flows_handler(event, context):
    environment = event['environment']

    return pytest.main(
        "-p no:cacheprovider -s --verbose --environment {env} ./test_retrieve_everything.py"
        .format(env=environment)
    )
