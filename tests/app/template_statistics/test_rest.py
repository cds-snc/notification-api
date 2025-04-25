import uuid
from unittest.mock import Mock

import pytest
from freezegun import freeze_time

from app.models import Template, TemplateHistory


def set_up_get_all_from_hash(mock_redis, side_effect):
    """
    redis returns binary strings for both keys and values - so given a list of side effects (return values),
    make sure
    """
    assert isinstance(side_effect, list)
    side_effects = []
    for ret_val in side_effect:
        if ret_val is None:
            side_effects.append(None)
        else:
            side_effects += [{str(k).encode('utf-8'): str(v).encode('utf-8') for k, v in ret_val.items()}]

    mock_redis.get_all_from_hash.side_effect = side_effects


# get_template_statistics_for_service_by_day


@pytest.mark.parametrize(
    'query_string',
    [
        {},
        {'whole_days': -1},
        {'whole_days': 8},
        {'whole_days': 3.5},
        {'whole_days': 'blurk'},
    ],
)
def test_get_template_statistics_for_service_by_day_with_bad_arg_returns_400(admin_request, query_string):
    json_resp = admin_request.get(
        'template_statistics.get_template_statistics_for_service_by_day',
        service_id=uuid.uuid4(),
        **query_string,
        _expected_status=400,
    )
    assert json_resp['result'] == 'error'
    assert 'whole_days' in json_resp['message']


def test_get_template_statistics_for_service_by_day_returns_template_info(
    notify_db_session,
    admin_request,
    mocker,
    sample_template,
    sample_notification,
):
    template = sample_template()
    notification = sample_notification(template=template)

    json_resp = admin_request.get(
        'template_statistics.get_template_statistics_for_service_by_day',
        service_id=notification.service_id,
        whole_days=1,
    )

    assert len(json_resp['data']) == 1

    assert json_resp['data'][0]['count'] == 1
    assert json_resp['data'][0]['template_id'] == str(template.id)
    assert json_resp['data'][0]['template_name'] == template.name
    assert json_resp['data'][0]['template_type'] == template.template_type
    assert json_resp['data'][0]['is_precompiled_letter'] is False

    # Teardown
    template = notify_db_session.session.get(Template, notification.template_id)
    template_history = notify_db_session.session.get(TemplateHistory, (template.id, template.version))
    notify_db_session.session.delete(notification)
    notify_db_session.session.delete(template_history)
    notify_db_session.session.commit()


@pytest.mark.parametrize('var_name', ['limit_days', 'whole_days'])
def test_get_template_statistics_for_service_by_day_accepts_old_query_string(
    admin_request,
    mocker,
    notify_db_session,
    sample_notification,
    sample_template,
    var_name,
):
    template = sample_template()
    notification = sample_notification(template=template)

    json_resp = admin_request.get(
        'template_statistics.get_template_statistics_for_service_by_day',
        service_id=template.service_id,
        **{var_name: 1},
    )

    assert len(json_resp['data']) == 1

    # Teardown
    template = notify_db_session.session.get(Template, notification.template_id)
    template_history = notify_db_session.session.get(TemplateHistory, (template.id, template.version))
    notify_db_session.session.delete(notification)
    notify_db_session.session.delete(template_history)
    notify_db_session.session.commit()


@freeze_time('2018-01-02 12:00:00')
def test_get_template_statistics_for_service_by_day_goes_to_db(admin_request, mocker, sample_template):
    template = sample_template()
    # first time it is called redis returns data, second time returns none
    mock_dao = mocker.patch(
        'app.template_statistics.rest.fetch_notification_status_for_service_for_today_and_7_previous_days',
        return_value=[
            Mock(
                template_id=template.id,
                count=3,
                template_name=template.name,
                notification_type=template.template_type,
                status='created',
                is_precompiled_letter=False,
            )
        ],
    )
    json_resp = admin_request.get(
        'template_statistics.get_template_statistics_for_service_by_day', service_id=template.service_id, whole_days=1
    )

    assert json_resp['data'] == [
        {
            'template_id': str(template.id),
            'count': 3,
            'template_name': template.name,
            'template_type': template.template_type,
            'status': 'created',
            'is_precompiled_letter': False,
        }
    ]
    # dao only called for 2nd, since redis returned values for first call
    mock_dao.assert_called_once_with(str(template.service_id), limit_days=1, by_template=True)


def test_get_template_statistics_for_service_by_day_returns_empty_list_if_no_templates(
    admin_request, mocker, sample_service
):
    json_resp = admin_request.get(
        'template_statistics.get_template_statistics_for_service_by_day', service_id=sample_service().id, whole_days=7
    )

    assert len(json_resp['data']) == 0
