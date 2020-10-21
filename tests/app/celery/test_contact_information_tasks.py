from app.celery.contact_information_tasks import lookup_contact_info, lookup_va_profile_id


def test_should_log_message_for_contact_information_tasks(client, mocker):
    mock_logger = mocker.patch('app.celery.contact_information_tasks.current_app.logger.info')

    lookup_contact_info()
    mock_logger.assert_called_with('This task will look up contact information.')

    lookup_va_profile_id()
    mock_logger.assert_called_with('This task will look up VA Profile ID.')
