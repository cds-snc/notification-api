from app.smtp.aws import (
    add_record,
    add_user,
    create_domain_identity,
    delete_record,
    generate_user_policy,
    get_dkim,
    munge,
    smtp_add,
    smtp_get_user_key,
    smtp_remove,
)


def test_smtp_add_adds_a_new_sender_domain(mocker, notify_api):
    create_domain_identity_mock = mocker.patch("app.smtp.aws.create_domain_identity")
    add_record_mock = mocker.patch("app.smtp.aws.add_record")
    get_dkim_mock = mocker.patch("app.smtp.aws.get_dkim")
    add_user_mock = mocker.patch("app.smtp.aws.add_user")

    with notify_api.app_context():
        smtp_add("foo")

    create_domain_identity_mock.assert_called_once()
    add_record_mock.assert_called()
    get_dkim_mock.assert_called_once()
    add_user_mock.assert_called_once()


def test_smtp_get_user_key(mocker, notify_api):
    boto_client = mocker.patch("app.smtp.aws.boto3")
    boto_client.client.list_access_keys.return_value = mocker.Mock()

    with notify_api.app_context():
        smtp_get_user_key("foo")

    boto_client.client.assert_called()


def test_smtp_remove_deletes_a_sender_domain(mocker, notify_api):
    boto_client = mocker.patch("app.smtp.aws.boto3")

    with notify_api.app_context():
        smtp_remove("foo-bbar")

    boto_client.client.assert_called()


def test_create_domain_identity_calls_verify_domain_identity(mocker, notify_api):
    client = mocker.Mock()
    client.verify_domain_identity.return_value = {"VerificationToken": ["FOO"]}

    with notify_api.app_context():
        create_domain_identity(client, "foo")

    client.verify_domain_identity.assert_called()


def test_get_dkim_calls_verify_domain_dkim(mocker, notify_api):
    client = mocker.Mock()
    client.verify_domain_dkim.return_value = {"DkimTokens": ["FOO"]}

    with notify_api.app_context():
        get_dkim(client, "foo")

    client.verify_domain_dkim.assert_called()


def test_add_user_creates_user_and_sets_policy(mocker, notify_api):
    client = mocker.Mock()
    client.create_access_key.return_value = {"AccessKey": {"AccessKeyId": "foo", "SecretAccessKey": "bar"}}

    with notify_api.app_context():
        add_user(client, "foo")

    client.create_user.assert_called()
    client.put_user_policy.assert_called()
    client.create_access_key.assert_called()


def test_add_record_calls_change_resource_record_sets(mocker, notify_api):
    client = mocker.Mock()

    with notify_api.app_context():
        add_record(client, "foo", "bar")

    client.change_resource_record_sets.assert_called()


def test_delete_record_calls_change_resource_record_sets(mocker, notify_api):
    client = mocker.Mock()

    with notify_api.app_context():
        delete_record(client, "foo")

    client.change_resource_record_sets.assert_called()


def test_generate_user_policy_restricts_policy_by_name():
    policy = (
        '{"Version":"2012-10-17","Statement":'
        '[{"Effect":"Allow","Action":["ses:SendRawEmail"],"Resource":"*",'
        '"Condition":{"StringLike":{"ses:FromAddress":"*@foo.bar"}}}]}')

    assert generate_user_policy("foo.bar") == policy


def test_munge_returns_an_smtp_secret():
    assert munge("wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY") == "An60U4ZD3sd4fg+FvXUjayOipTt8LO4rUUmhpdX6ctDy"
