import pytest
import os


@pytest.fixture
def all_path_env_param_set(monkeypatch):
    monkeypatch.setenv("DELIVERY_STATUS_RESULT_TASK_QUEUE", "DELIVERY_STATUS_RESULT_TASK_QUEUE")
    monkeypatch.setenv("DELIVERY_STATUS_RESULT_TASK_QUEUE_DEAD_LETTER", "DELIVERY_STATUS_RESULT_TASK_QUEUE_DEAD_LETTER")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("CELERY_TASK_NAME", "CELERY_TASK_NAME")
    monkeypatch.setenv("ROUTING_KEY", "ROUTING_KEY")


LAMBDA_MODULE = "lambda_functions.delivery_status_processor_lambda.delivery_status_processor_lambda"


@pytest.fixture(scope="function")
def event():
    """Generates a sample ALB received Twilio delivery status event object."""
    return {
        "requestContext": {"elb": {"targetGroupArn": "<DEV TARGET GROUP>"}},
        "httpMethod": "POST",
        "path": "/deliverystatus",
        "queryStringParameters": {},
        "headers": {
            "accept": "*/*",
            "connection": "close",
            "content-length": "227",
            "content-type": "application/x-www-form-urlencoded; charset=utf-8",
            "host": "dev-api.va.gov",
            "i-twilio-idempotency-token": "50609cf4-07f3-4e3f-ac42-044bd13bbc6c",
            "user-agent": "TwilioProxy/1.1",
            "x-amzn-trace-id": "Self=<SOME VALUE>",
            "x-forwarded-for": "<COMMA SEPARTED IPS>",
            "x-forwarded-host": "dev-api.va.gov:443",
            "x-forwarded-port": "443",
            "x-forwarded-proto": "https",
            "x-forwarded-scheme": "https",
            "x-home-region": "us1",
            "x-real-ip": "<SOME IP>",
            "x-twilio-signature": "<SOME VALUE>",
        },
        "body": "U21zU2lkPXRoaXNpc3NvbWVzbXNpZCZTbXNTdGF0dXM9c2VudCZNZXNzYWdlU3RhdHVzPXNlbnQmVG89JTJCMTExMTExMTExMTEmTWVzc2FnZVNpZD1zb21lbWVzc2FnZWlkZW50aWZpZXImQWNjb3VudFNpZD10d2lsaW9hY2NvdW50c2lkJkZyb209JTJCMjIyMjIyMjIyMiZBcGlWZXJzaW9uPTIwMTAtMDQtMDE=",
        "isBase64Encoded": True,
    }


def test_sys_exit_with_unset_queue_env_var(monkeypatch, all_path_env_param_set):
    monkeypatch.delenv("DELIVERY_STATUS_RESULT_TASK_QUEUE")

    with pytest.raises(SystemExit):
        from lambda_functions.delivery_status_processor_lambda.delivery_status_processor_lambda import (
            delivery_status_processor_lambda_handler,
        )


def test_sys_exit_with_unset_deadletter_queue_env_var(monkeypatch, all_path_env_param_set):
    monkeypatch.delenv("DELIVERY_STATUS_RESULT_TASK_QUEUE_DEAD_LETTER")

    with pytest.raises(SystemExit):
        from lambda_functions.delivery_status_processor_lambda.delivery_status_processor_lambda import (
            delivery_status_processor_lambda_handler,
        )


def test_invalid_event_event_none(mocker, all_path_env_param_set):
    from lambda_functions.delivery_status_processor_lambda.delivery_status_processor_lambda import (
        delivery_status_processor_lambda_handler,
    )

    sqs_mock = mocker.patch(f"{LAMBDA_MODULE}.push_to_sqs")

    event = None

    # Test a event is None
    delivery_status_processor_lambda_handler(event, None)

    sqs_mock.assert_called_once_with(event, os.getenv("DELIVERY_STATUS_RESULT_TASK_QUEUE_DEAD_LETTER"), False)


def test_invalid_event_body_none(mocker, event, all_path_env_param_set):
    from lambda_functions.delivery_status_processor_lambda.delivery_status_processor_lambda import (
        delivery_status_processor_lambda_handler,
    )

    # Test body not in event
    event.pop("body")

    sqs_mock = mocker.patch(f"{LAMBDA_MODULE}.push_to_sqs")

    # Test a event is None
    delivery_status_processor_lambda_handler(event, None)

    sqs_mock.assert_called_once_with(event, os.getenv("DELIVERY_STATUS_RESULT_TASK_QUEUE_DEAD_LETTER"), False)


def test_invalid_event_headers_none(mocker, event, all_path_env_param_set):
    from lambda_functions.delivery_status_processor_lambda.delivery_status_processor_lambda import (
        delivery_status_processor_lambda_handler,
    )

    # Test headers not in event["requestContext"]
    event.pop("headers")

    sqs_mock = mocker.patch(f"{LAMBDA_MODULE}.push_to_sqs")

    # Test a event is None
    delivery_status_processor_lambda_handler(event, None)

    sqs_mock.assert_called_once_with(event, os.getenv("DELIVERY_STATUS_RESULT_TASK_QUEUE_DEAD_LETTER"), False)


def test_invalid_event_user_agent_none(mocker, event, all_path_env_param_set):
    from lambda_functions.delivery_status_processor_lambda.delivery_status_processor_lambda import (
        delivery_status_processor_lambda_handler,
    )

    # Test user-agent not in event["requestContext"]["headers"]
    event["headers"].pop("user-agent")

    sqs_mock = mocker.patch(f"{LAMBDA_MODULE}.push_to_sqs")

    # Test a event is None
    delivery_status_processor_lambda_handler(event, None)

    sqs_mock.assert_called_once_with(event, os.getenv("DELIVERY_STATUS_RESULT_TASK_QUEUE_DEAD_LETTER"), False)


def test_valid_event(event, all_path_env_param_set):
    from lambda_functions.delivery_status_processor_lambda.delivery_status_processor_lambda import valid_event

    # Test valid event
    assert valid_event(event)


# TEST: event_to_celery_body_mapping() returns a dict with body and provider if headers.user-agent contains TwilioProxy


def test_event_to_celery_body_mapping_twilio_provider(event, all_path_env_param_set):
    from lambda_functions.delivery_status_processor_lambda.delivery_status_processor_lambda import (
        event_to_celery_body_mapping,
    )

    mapping_test = event_to_celery_body_mapping(event)

    assert "body" in mapping_test
    assert "provider" in mapping_test
    assert mapping_test["provider"] == "twilio"


def test_event_to_celery_body_mapping_non_twilio(event, all_path_env_param_set):
    from lambda_functions.delivery_status_processor_lambda.delivery_status_processor_lambda import (
        event_to_celery_body_mapping,
    )

    # Test non twilio user-agent
    event["headers"]["user-agent"] = "NON TWILIO USER AGENT"

    mapping_test = event_to_celery_body_mapping(event)

    assert mapping_test == None


def test_delivery_status_processor_lambda_handler_non_twilio_event(mocker, event, all_path_env_param_set):
    from lambda_functions.delivery_status_processor_lambda.delivery_status_processor_lambda import (
        delivery_status_processor_lambda_handler,
    )

    event["headers"]["user-agent"] = "NON TWILIO USER AGENT"

    sqs_mock = mocker.patch(f"{LAMBDA_MODULE}.push_to_sqs")

    # Test a event where the user-agent is not TwilioProxy
    delivery_status_processor_lambda_handler(event, None)

    sqs_mock.assert_called_once_with(event, os.getenv("DELIVERY_STATUS_RESULT_TASK_QUEUE_DEAD_LETTER"), False)


# TEST: celery_body_to_celery_task() returns a dict with an envelope that has a body = base 64 encoded task and that base 64 encoded task  contains Message key with the task_message
