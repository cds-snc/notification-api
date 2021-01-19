def test_email_from_domain_is_not_set(mock_email_client):
    assert mock_email_client.email_from_domain is None


def test_email_from_user_is_not_set(mock_email_client):
    assert mock_email_client.email_from_user is None
