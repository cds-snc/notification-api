import uuid
from random import choices
from string import digits

import pytest

from app.models import InboundNumber


class TestGetInboundNumbers:
    def test_returns_empty_list_when_no_inbound_numbers(self, admin_request, mocker):
        mocker.patch('app.inbound_number.rest.dao_get_inbound_numbers', return_value=[])

        result = admin_request.get('inbound_number.get_inbound_numbers')

        assert result['data'] == []

    def test_returns_inbound_numbers(self, admin_request, mocker):
        inbound_number = InboundNumber()
        mocker.patch('app.inbound_number.rest.dao_get_inbound_numbers', return_value=[inbound_number])

        result = admin_request.get('inbound_number.get_inbound_numbers')

        assert result['data'] == [inbound_number.serialize()]


class TestGetInboundNumbersForService:
    def test_gets_empty_list(self, admin_request, mocker):
        dao_get_inbound_numbers_for_service = mocker.patch(
            'app.inbound_number.rest.dao_get_inbound_numbers_for_service', return_value=[]
        )

        service_id = uuid.uuid4()
        result = admin_request.get('inbound_number.get_inbound_numbers_for_service', service_id=service_id)

        assert result['data'] == []
        dao_get_inbound_numbers_for_service.assert_called_with(service_id)

    def test_gets_inbound_numbers(self, admin_request, mocker):
        inbound_number = InboundNumber()
        mocker.patch('app.inbound_number.rest.dao_get_inbound_numbers_for_service', return_value=[inbound_number])

        result = admin_request.get('inbound_number.get_inbound_numbers_for_service', service_id=uuid.uuid4())

        assert result['data'] == [inbound_number.serialize()]


class TestSetInboundNumberOff:
    def test_sets_inbound_number_active_flag_off(self, admin_request, mocker):
        dao_set_inbound_number_active_flag = mocker.patch('app.inbound_number.rest.dao_set_inbound_number_active_flag')

        inbound_number_id = uuid.uuid4()
        admin_request.post(
            'inbound_number.post_set_inbound_number_off', _expected_status=204, inbound_number_id=inbound_number_id
        )
        dao_set_inbound_number_active_flag.assert_called_with(inbound_number_id, active=False)


@pytest.mark.serial
def test_get_available_inbound_numbers_returns_empty_list(admin_request):
    # Cannot be ran in parallel - Grabs all
    result = admin_request.get('inbound_number.get_available_inbound_numbers')

    assert result['data'] == []


@pytest.mark.serial
def test_get_available_inbound_numbers(
    admin_request,
    sample_inbound_numbers,
):
    # Cannot be ran in parallel - Grabs all
    result = admin_request.get('inbound_number.get_available_inbound_numbers')

    assert len(result['data']) == 1
    assert result['data'] == [i.serialize() for i in sample_inbound_numbers if i.service_id is None]


class TestCreateInboundNumber:
    def test_rejects_request_with_missing_data(self, admin_request):
        admin_request.post('inbound_number.create_inbound_number', _data={}, _expected_status=400)

    def test_rejects_request_with_unexpected_data(self, admin_request):
        admin_request.post(
            'inbound_number.create_inbound_number',
            _data={
                'number': ''.join(choices(digits, k=12)),
                'provider': 'some-provider',
                'service_id': 'some-service-id',
                'some_attribute_that_does_not_exist': 'blah',
            },
            _expected_status=400,
        )

    def test_rejects_missing_url_endpoint(self, admin_request):
        """
        url_endpoint is required because self_managed is True.
        """

        admin_request.post(
            'inbound_number.create_inbound_number',
            _data={
                'number': ''.join(choices(digits, k=12)),
                'provider': 'some-provider',
                'self_managed': True,
            },
            _expected_status=400,
        )

    def test_rejects_duplicate_number(self, sample_inbound_number, admin_request):
        """
        The number must be unique.
        """

        inbound_number = sample_inbound_number(number=''.join(choices(digits, k=12)))

        response = admin_request.post(
            'inbound_number.create_inbound_number',
            _data={
                'number': inbound_number.number,
                'provider': 'some-provider',
                'self_managed': False,
            },
            _expected_status=400,
        )

        assert response['errors'][0]['error'] == 'IntegrityError'
        assert 'duplicate key value violates unique constraint' in response['errors'][0]['message']

    @pytest.mark.parametrize(
        'post_data',
        [
            # url_endpoint is not required because self_managed is not present.
            {
                'provider': 'some-provider',
            },
            # url_endpoint is not required because self_managed is False.
            {
                'provider': 'some-provider',
                'self_managed': False,
            },
            # url_endpoint is required because self_managed is True.
            {
                'provider': 'some-provider',
                'url_endpoint': 'https://example.foo',
                'self_managed': True,
            },
        ],
    )
    def test_creates_inbound_number(self, admin_request, sample_service, post_data):
        """
        The request should be valid because it has all the required attributes.
        """

        # The number must be unique.
        post_data['number'] = ''.join(choices(digits, k=12))

        service = sample_service()
        post_data['service_id'] = str(service.id)

        response = admin_request.post('inbound_number.create_inbound_number', _data=post_data, _expected_status=201)

        assert response['data']['number'] == post_data['number']
        assert response['data']['provider'] == post_data['provider']
        assert response['data']['service']['id'] == post_data['service_id']


class TestUpdateInboundNumber:
    @pytest.fixture(autouse=True)
    def setup(self, sample_inbound_number):
        self.inbound_number = sample_inbound_number(number=''.join(choices(digits, k=12)))
        self.inbound_number2 = sample_inbound_number(number=''.join(choices(digits, k=12)))
        assert not self.inbound_number.self_managed

    def test_rejects_invalid_request(self, admin_request):
        response = admin_request.post(
            'inbound_number.update_inbound_number',
            _data={'some_attribute_that_does_not_exist': 'blah'},
            _expected_status=400,
            inbound_number_id=self.inbound_number.id,
        )

        assert response['errors'][0]['error'] == 'ValidationError'
        assert 'Additional properties are not allowed' in response['errors'][0]['message']

    def test_rejects_missing_url_endpoint(self, admin_request):
        """
        url_endpoint is required because self_managed is True.
        """

        response = admin_request.post(
            'inbound_number.update_inbound_number',
            _data={'self_managed': True},
            _expected_status=400,
            inbound_number_id=self.inbound_number.id,
        )

        assert response['errors'][0]['error'] == 'ValidationError'
        assert 'url_endpoint is a required property' in response['errors'][0]['message']

    def test_rejects_duplicate_number(self, admin_request):
        """
        The number must be unique.
        """

        response = admin_request.post(
            'inbound_number.update_inbound_number',
            _data={'number': self.inbound_number2.number},
            _expected_status=400,
            inbound_number_id=self.inbound_number.id,
        )

        print(response)
        assert response['errors'][0]['error'] == 'IntegrityError'
        assert 'duplicate key value violates unique constraint' in response['errors'][0]['message']

    @pytest.mark.parametrize(
        'update_data',
        [
            # A number and provider are not requires for an update.
            {
                'active': False,
            },
            # url_endpoint is not required because self_managed is not present.
            {
                'provider': 'some-provider',
            },
            # url_endpoint is not required because self_managed is False.
            {
                'provider': 'some-provider',
                'self_managed': False,
            },
            # url_endpoint is required because self_managed is True.
            {
                'provider': 'some-provider',
                'url_endpoint': 'https://example.foo',
                'self_managed': True,
            },
        ],
    )
    def test_updates_inbound_number(self, admin_request, sample_service, update_data):
        """
        The request should be valid because it has all the required attributes.
        """

        service = sample_service()
        update_data['service_id'] = str(service.id)

        response = admin_request.post(
            'inbound_number.update_inbound_number',
            _data=update_data,
            _expected_status=200,
            inbound_number_id=self.inbound_number.id,
        )

        assert response['data'] == self.inbound_number.serialize()
