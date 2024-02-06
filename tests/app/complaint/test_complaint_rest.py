from datetime import date

from flask import url_for
from freezegun import freeze_time
import pytest

from tests import create_admin_authorization_header


def test_get_all_complaints_returns_complaints_for_multiple_services(client, sample_complaint):
    complaint_1 = sample_complaint()
    complaint_2 = sample_complaint()
    assert complaint_1.service_id != complaint_2.service_id

    response = client.get('/complaint', headers=[create_admin_authorization_header()])

    assert response.status_code == 200
    assert response.get_json()['complaints'] == [complaint_2.serialize(), complaint_1.serialize()]


@pytest.mark.serial
def test_get_all_complaints_returns_empty_complaints_list(client):
    response = client.get('/complaint', headers=[create_admin_authorization_header()])

    assert response.status_code == 200
    assert response.get_json()['complaints'] == []


@pytest.mark.serial
def test_get_all_complaints_returns_pagination_links(mocker, client, sample_complaint):
    mocker.patch.dict('app.dao.complaint_dao.current_app.config', {'PAGE_SIZE': 1})

    sample_complaint()
    sample_complaint()
    sample_complaint()

    # serial request
    response = client.get(
        url_for('complaint.get_all_complaints', page=2), headers=[create_admin_authorization_header()]
    )

    assert response.status_code == 200
    assert response.get_json()['links'] == {
        'last': '/complaint?page=3',
        'next': '/complaint?page=3',
        'prev': '/complaint?page=1',
    }


def test_get_complaint_with_start_and_end_date_passes_these_to_dao_function(mocker, client):
    start_date = date(2018, 6, 11)
    end_date = date(2018, 6, 11)
    dao_mock = mocker.patch('app.complaint.complaint_rest.fetch_count_of_complaints', return_value=3)
    response = client.get(
        url_for('complaint.get_complaint_count', start_date=start_date, end_date=end_date),
        headers=[create_admin_authorization_header()],
    )

    dao_mock.assert_called_once_with(start_date=start_date, end_date=end_date)
    assert response.status_code == 200
    assert response.get_json() == 3


@freeze_time('2018-06-01 11:00:00')
def test_get_complaint_sets_start_and_end_date_to_today_if_not_specified(mocker, client):
    dao_mock = mocker.patch('app.complaint.complaint_rest.fetch_count_of_complaints', return_value=5)
    response = client.get(url_for('complaint.get_complaint_count'), headers=[create_admin_authorization_header()])

    dao_mock.assert_called_once_with(start_date=date.today(), end_date=date.today())
    assert response.status_code == 200
    assert response.get_json() == 5


def test_get_complaint_with_invalid_data_returns_400_status_code(client):
    start_date = '1234-56-78'
    response = client.get(
        url_for('complaint.get_complaint_count', start_date=start_date), headers=[create_admin_authorization_header()]
    )

    assert response.status_code == 400
    assert response.json['errors'][0]['message'] == 'start_date month must be in 1..12'
