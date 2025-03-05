import pytest
from flask import url_for

from app.constants import (
    DATETIME_FORMAT,
    EMAIL_TYPE,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_TEMPORARY_FAILURE,
    SMS_TYPE,
)
from app.va.identifier import IdentifierType
from tests import create_authorization_header


@pytest.mark.parametrize('billable_units, provider', [(1, 'mmg'), (0, 'mmg'), (1, None)])
def test_get_notification_by_id_returns_200(
    client,
    billable_units,
    provider,
    sample_api_key,
    sample_template,
    sample_notification,
):
    """This test assumes the local timezone is EST."""
    template = sample_template()
    first_notification = sample_notification(
        template=template,
        billable_units=billable_units,
        sent_by=provider,
        scheduled_for='2017-05-12 15:15',
        billing_code='billing_code',
        callback_url='https://www.test.com',
    )

    sample_notification(
        template=template, billable_units=billable_units, sent_by=provider, scheduled_for='2017-06-12 15:15'
    )

    auth_header = create_authorization_header(sample_api_key(service=template.service))
    response = client.get(
        path='/v2/notifications/{}'.format(first_notification.id),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    assert response.status_code == 200
    assert response.headers['Content-type'] == 'application/json'

    expected_template_response = {
        'id': '{}'.format(first_notification.serialize()['template']['id']),
        'version': first_notification.serialize()['template']['version'],
        'uri': first_notification.serialize()['template']['uri'],
    }

    expected_response = {
        'id': '{}'.format(first_notification.id),
        'reference': first_notification.client_reference,
        'provider_reference': first_notification.reference,
        'email_address': None,
        'phone_number': '{}'.format(first_notification.to),
        'line_1': None,
        'line_2': None,
        'line_3': None,
        'line_4': None,
        'line_5': None,
        'line_6': None,
        'postcode': None,
        'type': '{}'.format(first_notification.notification_type),
        'status': '{}'.format(first_notification.status),
        'status_reason': None,
        'template': expected_template_response,
        'created_at': first_notification.created_at.strftime(DATETIME_FORMAT),
        'created_by_name': 'Test User',
        'body': first_notification.template.content,
        'subject': None,
        'sent_at': first_notification.sent_at,
        'sent_by': provider,
        'completed_at': first_notification.completed_at(),
        'scheduled_for': '2017-05-12T19:15:00.000000Z',
        'postage': None,
        'recipient_identifiers': [],
        'billing_code': first_notification.billing_code,
        'sms_sender_id': None,
        'cost_in_millicents': 0.0,
        'segments_count': 0,
        'callback_url': 'https://www.test.com',
    }

    assert response.get_json() == expected_response


@pytest.mark.parametrize(
    'recipient_identifiers', [None, [{'id_type': IdentifierType.VA_PROFILE_ID.value, 'id_value': 'some vaprofileid'}]]
)
def test_get_notification_by_id_with_placeholders_and_recipient_identifiers_returns_200(
    client,
    sample_api_key,
    sample_template,
    sample_notification,
    recipient_identifiers,
):
    template = sample_template(template_type=EMAIL_TYPE, content='Hello ((name))\nThis is an email from va.gov')
    notification = sample_notification(
        template=template,
        personalisation={'name': 'Bob'},
        recipient_identifiers=recipient_identifiers,
        callback_url='https://www.test.com',
    )

    auth_header = create_authorization_header(sample_api_key(service=template.service))
    response = client.get(
        path=url_for('v2_notifications.get_notification_by_id', notification_id=notification.id),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    assert response.status_code == 200
    assert response.headers['Content-type'] == 'application/json'

    expected_template_response = {
        'id': '{}'.format(notification.serialize()['template']['id']),
        'version': notification.serialize()['template']['version'],
        'uri': notification.serialize()['template']['uri'],
    }

    expected_response = {
        'id': str(notification.id),
        'reference': None,
        'provider_reference': notification.reference,
        'email_address': '{}'.format(notification.to),
        'phone_number': None,
        'line_1': None,
        'line_2': None,
        'line_3': None,
        'line_4': None,
        'line_5': None,
        'line_6': None,
        'postcode': None,
        'type': '{}'.format(notification.notification_type),
        'status': '{}'.format(notification.status),
        'status_reason': None,
        'template': expected_template_response,
        'created_at': notification.created_at.strftime(DATETIME_FORMAT),
        'created_by_name': 'Test User',
        'body': 'Hello <redacted>\nThis is an email from va.gov',
        'subject': 'Subject',
        'sent_at': notification.sent_at,
        'sent_by': None,
        'completed_at': notification.completed_at(),
        'scheduled_for': None,
        'postage': None,
        'recipient_identifiers': recipient_identifiers if recipient_identifiers else [],
        'billing_code': None,
        'sms_sender_id': None,
        'cost_in_millicents': 0.0,
        'segments_count': 0,
        'callback_url': 'https://www.test.com',
    }

    assert response.get_json() == expected_response


def test_get_notification_by_reference_returns_200(
    client,
    sample_api_key,
    sample_template,
    sample_notification,
):
    sample_notification_with_reference = sample_notification(
        template=sample_template(), client_reference='some-client-reference'
    )

    auth_header = create_authorization_header(sample_api_key(service=sample_notification_with_reference.service))
    response = client.get(
        path='/v2/notifications?reference={}'.format(sample_notification_with_reference.client_reference),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    assert response.status_code == 200
    assert response.headers['Content-type'] == 'application/json'

    json_response = response.get_json()
    assert len(json_response['notifications']) == 1

    assert json_response['notifications'][0]['id'] == str(sample_notification_with_reference.id)
    assert json_response['notifications'][0]['reference'] == 'some-client-reference'


def test_get_notification_by_id_returns_created_by_name_if_notification_created_by_id(
    client,
    sample_api_key,
    sample_template,
    sample_notification,
    sample_user,
):
    user = sample_user()
    template = sample_template(user=user)
    sms_notification = sample_notification(template=template, created_by_id=user.id)

    auth_header = create_authorization_header(sample_api_key(service=template.service))
    response = client.get(
        path=url_for('v2_notifications.get_notification_by_id', notification_id=sms_notification.id),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    json_response = response.get_json()
    assert json_response['created_by_name'] == 'Test User'


# This test assumes the local timezone is EST
def test_get_notifications_returns_scheduled_for(
    client,
    sample_api_key,
    sample_template,
    sample_notification,
):
    notification_with_ref = sample_notification(
        template=sample_template(), client_reference='some-client-reference', scheduled_for='2017-05-23 17:15'
    )

    auth_header = create_authorization_header(sample_api_key(service=notification_with_ref.service))
    response = client.get(
        path='/v2/notifications?reference={}'.format(notification_with_ref.client_reference),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    assert response.status_code == 200
    assert response.headers['Content-type'] == 'application/json'

    json_response = response.get_json()
    assert len(json_response['notifications']) == 1

    assert json_response['notifications'][0]['id'] == str(notification_with_ref.id)
    assert json_response['notifications'][0]['scheduled_for'] == '2017-05-23T21:15:00.000000Z'


def test_get_notification_by_reference_nonexistent_reference_returns_no_notifications(
    client,
    sample_api_key,
):
    auth_header = create_authorization_header(sample_api_key())
    response = client.get(
        path='/v2/notifications?reference={}'.format('nonexistent-reference'),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    json_response = response.get_json()

    assert response.status_code == 200
    assert response.headers['Content-type'] == 'application/json'
    assert len(json_response['notifications']) == 0


def test_get_notification_by_id_nonexistent_id(
    client,
    sample_api_key,
    sample_template,
):
    template = sample_template()
    auth_header = create_authorization_header(sample_api_key(service=template.service))

    response = client.get(
        path='/v2/notifications/dd4b8b9d-d414-4a83-9256-580046bf18f9',
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    assert response.status_code == 404
    assert response.headers['Content-type'] == 'application/json'

    json_response = response.get_json()
    assert json_response == {'errors': [{'error': 'NoResultFound', 'message': 'No result found'}], 'status_code': 404}


@pytest.mark.parametrize('id', ['1234-badly-formatted-id-7890', '0'])
def test_get_notification_by_id_invalid_id(
    client,
    sample_api_key,
    sample_template,
    id,
):
    template = sample_template()
    auth_header = create_authorization_header(sample_api_key(service=template.service))
    response = client.get(
        path='/v2/notifications/{}'.format(id), headers=[('Content-Type', 'application/json'), auth_header]
    )

    assert response.status_code == 400
    assert response.headers['Content-type'] == 'application/json'

    json_response = response.get_json()
    assert json_response == {
        'errors': [{'error': 'ValidationError', 'message': 'notification_id is not a valid UUID'}],
        'status_code': 400,
    }


@pytest.mark.parametrize('template_type', [SMS_TYPE, EMAIL_TYPE])
def test_get_notification_doesnt_have_delivery_estimate_for_non_letters(
    client,
    sample_api_key,
    sample_template,
    sample_notification,
    template_type,
):
    template = sample_template(template_type=template_type)
    mocked_notification = sample_notification(template=template)

    auth_header = create_authorization_header(sample_api_key(service=mocked_notification.service))
    response = client.get(
        path='/v2/notifications/{}'.format(mocked_notification.id),
        headers=[('Content-Type', 'application/json'), auth_header],
    )
    assert response.status_code == 200
    assert 'estimated_delivery' not in response.get_json()


def test_get_all_notifications_except_job_notifications_returns_200(
    client,
    sample_api_key,
    sample_template,
    sample_notification,
    sample_job,
):
    template = sample_template()
    job = sample_job(template=template)
    sample_notification(template=template, job=job)  # should not return this job notification
    notifications = [sample_notification(template=template) for _ in range(2)]
    notification = notifications[-1]

    auth_header = create_authorization_header(sample_api_key(service=template.service))
    response = client.get(path='/v2/notifications', headers=[('Content-Type', 'application/json'), auth_header])

    json_response = response.get_json()

    assert response.status_code == 200
    assert response.headers['Content-type'] == 'application/json'
    assert json_response['links']['current'].endswith('/v2/notifications')
    assert 'next' in json_response['links'].keys()
    assert len(json_response['notifications']) == 2

    assert json_response['notifications'][0]['id'] == str(notification.id)
    assert json_response['notifications'][0]['status'] == 'created'
    assert json_response['notifications'][0]['template'] == {
        'id': str(notification.template.id),
        'uri': notification.template.get_link(),
        'version': 1,
    }
    assert json_response['notifications'][0]['phone_number'] == '+16502532222'
    assert json_response['notifications'][0]['type'] == SMS_TYPE
    assert not json_response['notifications'][0]['scheduled_for']


def test_get_all_notifications_with_include_jobs_arg_returns_200(
    client,
    sample_api_key,
    sample_template,
    sample_notification,
    sample_job,
):
    template = sample_template()
    job = sample_job(template=template)
    notifications = [sample_notification(template=template, job=job), sample_notification(template=template)]
    notification = notifications[-1]

    auth_header = create_authorization_header(sample_api_key(service=template.service))
    # We are not using the "jobs" functionality
    response = client.get(
        path='/v2/notifications?include_jobs=true', headers=[('Content-Type', 'application/json'), auth_header]
    )

    json_response = response.get_json()

    assert response.status_code == 200
    assert json_response['links']['current'].endswith('/v2/notifications?include_jobs=true')
    assert 'next' in json_response['links'].keys()
    assert len(json_response['notifications']) == 2

    assert json_response['notifications'][0]['id'] == str(notification.id)
    assert json_response['notifications'][0]['status'] == notification.status
    assert json_response['notifications'][0]['phone_number'] == notification.to
    assert json_response['notifications'][0]['type'] == notification.template.template_type
    assert not json_response['notifications'][0]['scheduled_for']


def test_get_all_notifications_no_notifications_if_no_notifications(
    client,
    sample_api_key,
):
    auth_header = create_authorization_header(sample_api_key())
    response = client.get(path='/v2/notifications', headers=[('Content-Type', 'application/json'), auth_header])

    json_response = response.get_json()

    assert response.status_code == 200
    assert response.headers['Content-type'] == 'application/json'
    assert json_response['links']['current'].endswith('/v2/notifications')
    assert 'next' not in json_response['links'].keys()
    assert len(json_response['notifications']) == 0


def test_get_all_notifications_filter_by_template_type(
    client,
    sample_api_key,
    sample_service,
    sample_template,
    sample_notification,
):
    service = sample_service()
    email_template = sample_template(service=service, template_type=EMAIL_TYPE)
    sms_template = sample_template(service=service, template_type=SMS_TYPE)

    notification = sample_notification(template=email_template, to_field='don.draper@scdp.biz')
    sample_notification(template=sms_template)

    auth_header = create_authorization_header(sample_api_key(service=email_template.service))
    response = client.get(
        path='/v2/notifications?template_type=email', headers=[('Content-Type', 'application/json'), auth_header]
    )

    json_response = response.get_json()

    assert response.status_code == 200
    assert response.headers['Content-type'] == 'application/json'
    assert json_response['links']['current'].endswith('/v2/notifications?template_type=email')
    assert 'next' in json_response['links'].keys()
    assert len(json_response['notifications']) == 1

    assert json_response['notifications'][0]['id'] == str(notification.id)
    assert json_response['notifications'][0]['status'] == 'created'
    assert json_response['notifications'][0]['template'] == {
        'id': str(email_template.id),
        'uri': notification.template.get_link(),
        'version': 1,
    }
    assert json_response['notifications'][0]['email_address'] == 'don.draper@scdp.biz'
    assert json_response['notifications'][0]['type'] == EMAIL_TYPE


def test_get_all_notifications_filter_by_template_type_invalid_template_type(
    client,
    sample_api_key,
):
    auth_header = create_authorization_header(sample_api_key())
    response = client.get(
        path='/v2/notifications?template_type=orange', headers=[('Content-Type', 'application/json'), auth_header]
    )

    json_response = response.get_json()

    assert response.status_code == 400
    assert response.headers['Content-type'] == 'application/json'

    assert json_response['status_code'] == 400
    assert len(json_response['errors']) == 1
    assert json_response['errors'][0]['message'] == 'template_type orange is not one of (sms, email, letter)'


def test_get_all_notifications_filter_by_single_status(
    client,
    sample_api_key,
    sample_template,
    sample_notification,
):
    template = sample_template()
    notification = sample_notification(template=template, status='pending')
    sample_notification(template=template)

    auth_header = create_authorization_header(sample_api_key(service=template.service))
    response = client.get(
        path='/v2/notifications?status=pending', headers=[('Content-Type', 'application/json'), auth_header]
    )

    json_response = response.get_json()

    assert response.status_code == 200
    assert response.headers['Content-type'] == 'application/json'
    assert json_response['links']['current'].endswith('/v2/notifications?status=pending')
    assert 'next' in json_response['links'].keys()
    assert len(json_response['notifications']) == 1

    assert json_response['notifications'][0]['id'] == str(notification.id)
    assert json_response['notifications'][0]['status'] == 'pending'


def test_get_all_notifications_filter_by_status_invalid_status(
    client,
    sample_api_key,
    sample_notification,
    sample_template,
):
    fake_status = 'non-existant-status'
    api_key = sample_api_key()
    sample_notification(template=sample_template(service=api_key.service))
    auth_header = create_authorization_header(api_key)

    response = client.get(
        path=f'/v2/notifications?status={fake_status}', headers=[('Content-Type', 'application/json'), auth_header]
    )

    json_response = response.get_json()

    assert response.status_code == 400
    assert response.headers['Content-type'] == 'application/json'

    assert json_response['status_code'] == 400
    assert len(json_response['errors']) == 1
    assert f'status {fake_status} is not one of' in json_response['errors'][0]['message']


def test_get_all_notifications_filter_by_multiple_statuses(
    client,
    sample_api_key,
    sample_template,
    sample_notification,
):
    template = sample_template()
    notifications = [
        sample_notification(template=template, status=_status) for _status in ['created', 'pending', 'sending']
    ]
    failed_notification = sample_notification(template=template, status='permanent-failure')

    auth_header = create_authorization_header(sample_api_key(service=template.service))
    response = client.get(
        path='/v2/notifications?status=created&status=pending&status=sending',
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    json_response = response.get_json()

    assert response.status_code == 200
    assert response.headers['Content-type'] == 'application/json'
    assert json_response['links']['current'].endswith('/v2/notifications?status=created&status=pending&status=sending')
    assert 'next' in json_response['links'].keys()
    assert len(json_response['notifications']) == 3

    returned_notification_ids = [_n['id'] for _n in json_response['notifications']]
    for _id in [_notification.id for _notification in notifications]:
        assert str(_id) in returned_notification_ids

    assert failed_notification.id not in returned_notification_ids


def test_get_all_notifications_filter_by_failed_status(
    client,
    sample_api_key,
    sample_template,
    sample_notification,
):
    template = sample_template()
    created_notification = sample_notification(template=template, status='created')
    failed_notifications = [
        sample_notification(template=template, status=_status)
        for _status in [NOTIFICATION_TEMPORARY_FAILURE, NOTIFICATION_PERMANENT_FAILURE, NOTIFICATION_PERMANENT_FAILURE]
    ]

    auth_header = create_authorization_header(sample_api_key(service=template.service))
    response = client.get(
        path='/v2/notifications?status=failed', headers=[('Content-Type', 'application/json'), auth_header]
    )

    json_response = response.get_json()

    assert response.status_code == 200
    assert response.headers['Content-type'] == 'application/json'
    assert json_response['links']['current'].endswith('/v2/notifications?status=failed')
    assert 'next' in json_response['links'].keys()
    assert len(json_response['notifications']) == 3

    returned_notification_ids = [n['id'] for n in json_response['notifications']]
    for _id in [_notification.id for _notification in failed_notifications]:
        assert str(_id) in returned_notification_ids

    assert created_notification.id not in returned_notification_ids


def test_get_all_notifications_filter_by_id(
    client,
    sample_api_key,
    sample_template,
    sample_notification,
):
    template = sample_template()
    older_notification = sample_notification(template=template)
    newer_notification = sample_notification(template=template)

    auth_header = create_authorization_header(sample_api_key(service=template.service))
    response = client.get(
        path='/v2/notifications?older_than={}'.format(newer_notification.id),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    json_response = response.get_json()

    assert response.status_code == 200
    assert response.headers['Content-type'] == 'application/json'
    assert json_response['links']['current'].endswith('/v2/notifications?older_than={}'.format(newer_notification.id))
    assert 'next' in json_response['links'].keys()
    assert len(json_response['notifications']) == 1

    assert json_response['notifications'][0]['id'] == str(older_notification.id)


def test_get_all_notifications_filter_by_id_invalid_id(
    client,
    sample_api_key,
):
    auth_header = create_authorization_header(sample_api_key())
    response = client.get(
        path='/v2/notifications?older_than=1234-badly-formatted-id-7890',
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    json_response = response.get_json()

    assert json_response['status_code'] == 400
    assert len(json_response['errors']) == 1
    assert json_response['errors'][0]['message'] == 'older_than is not a valid UUID'


def test_get_all_notifications_filter_by_id_no_notifications_if_nonexistent_id(
    client,
    sample_api_key,
    sample_template,
    sample_notification,
):
    template = sample_template()
    sample_notification(template=template)

    auth_header = create_authorization_header(sample_api_key(service=template.service))
    response = client.get(
        path='/v2/notifications?older_than=dd4b8b9d-d414-4a83-9256-580046bf18f9',
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    json_response = response.get_json()

    assert response.status_code == 200
    assert response.headers['Content-type'] == 'application/json'
    assert json_response['links']['current'].endswith(
        '/v2/notifications?older_than=dd4b8b9d-d414-4a83-9256-580046bf18f9'
    )
    assert 'next' not in json_response['links'].keys()
    assert len(json_response['notifications']) == 0


def test_get_all_notifications_filter_by_id_no_notifications_if_last_notification(
    client,
    sample_api_key,
    sample_template,
    sample_notification,
):
    template = sample_template()
    notification = sample_notification(template=template)

    auth_header = create_authorization_header(sample_api_key(service=template.service))
    response = client.get(
        path='/v2/notifications?older_than={}'.format(notification.id),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    json_response = response.get_json()

    assert response.status_code == 200
    assert response.headers['Content-type'] == 'application/json'
    assert json_response['links']['current'].endswith('/v2/notifications?older_than={}'.format(notification.id))
    assert 'next' not in json_response['links'].keys()
    assert len(json_response['notifications']) == 0


def test_get_all_notifications_filter_multiple_query_parameters(
    client,
    sample_api_key,
    sample_template,
    sample_notification,
):
    template = sample_template(template_type=EMAIL_TYPE)
    api_key = sample_api_key(service=template.service)
    # this is the notification we are looking for
    older_notification = sample_notification(template=template, status='pending')

    # wrong status
    sample_notification(template=template)
    wrong_template = sample_template(service=template.service, template_type=SMS_TYPE)
    # wrong template
    sample_notification(template=wrong_template, status='pending')

    # we only want notifications created before this one
    newer_notification = sample_notification(template=template)

    # this notification was created too recently
    sample_notification(template=template, status='pending')

    auth_header = create_authorization_header(api_key)
    response = client.get(
        path='/v2/notifications?status=pending&template_type=email&older_than={}'.format(newer_notification.id),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    json_response = response.get_json()

    assert response.status_code == 200
    assert response.headers['Content-type'] == 'application/json'
    # query parameters aren't returned in order
    for url_part in [
        '/v2/notifications?',
        'template_type=email',
        'status=pending',
        'older_than={}'.format(newer_notification.id),
    ]:
        assert url_part in json_response['links']['current']

    assert 'next' in json_response['links'].keys()
    assert len(json_response['notifications']) == 1

    assert json_response['notifications'][0]['id'] == str(older_notification.id)


@pytest.mark.parametrize('template_type', [SMS_TYPE, EMAIL_TYPE])
def test_get_notifications_removes_personalisation_from_content(
    client,
    sample_api_key,
    sample_notification,
    sample_template,
    template_type,
):
    template = sample_template(
        content='Hello ((name))\nThis is an email from VA Notify about some ((thing))',
        template_type=template_type,
    )
    notification = sample_notification(
        template=template,
        personalisation={'name': 'Bob', 'thing': 'important stuff'},
    )
    auth_header = create_authorization_header(sample_api_key(service=template.service))
    response = client.get(
        path=url_for('v2_notifications.get_notification_by_id', notification_id=notification.id),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    json_response = response.get_json()
    assert response.status_code == 200
    assert json_response['body'] == 'Hello <redacted>\nThis is an email from VA Notify about some <redacted>'


def test_get_notifications_removes_personalisation_from_subject(
    client,
    sample_api_key,
    sample_notification,
    sample_template,
):
    template = sample_template(
        subject='Hello ((name))',
        content='This is an email',
        template_type=EMAIL_TYPE,
    )
    notification = sample_notification(
        template=template,
        personalisation={'name': 'Bob'},
    )
    auth_header = create_authorization_header(sample_api_key(service=template.service))
    response = client.get(
        path=url_for('v2_notifications.get_notification_by_id', notification_id=notification.id),
        headers=[('Content-Type', 'application/json'), auth_header],
    )

    json_response = response.get_json()
    assert response.status_code == 200
    assert json_response['subject'] == 'Hello <redacted>'


def test_get_notification_by_id_redacts_icn(client, sample_api_key, sample_template, sample_notification):
    notification = sample_notification(
        template=sample_template(), recipient_identifiers=[{'id_type': IdentifierType.ICN.value, 'id_value': 'icn'}]
    )
    assert notification.recipient_identifiers['ICN'].id_value == 'icn'
    auth_header = create_authorization_header(sample_api_key(service=notification.template.service))

    response = client.get(
        path=url_for('v2_notifications.get_notification_by_id', notification_id=notification.id),
        headers=[('Content-Type', 'application/json'), auth_header],
    ).get_json()

    assert response['recipient_identifiers'][0]['id_type'] == 'ICN'
    assert response['recipient_identifiers'][0]['id_value'] == '<redacted>'


@pytest.mark.serial
def test_get_notifications_redacts_icn(client, sample_api_key, sample_template, sample_notification):
    notification = sample_notification(
        template=sample_template(), recipient_identifiers=[{'id_type': IdentifierType.ICN.value, 'id_value': 'icn'}]
    )
    assert notification.recipient_identifiers['ICN'].id_value == 'icn'
    auth_header = create_authorization_header(sample_api_key(service=notification.template.service))

    response = client.get(
        path=url_for('v2_notifications.get_notifications'), headers=[('Content-Type', 'application/json'), auth_header]
    ).get_json()

    assert response['notifications'][0]['recipient_identifiers'][0]['id_type'] == 'ICN'
    assert response['notifications'][0]['recipient_identifiers'][0]['id_value'] == '<redacted>'
