from app.models import CommunicationItem


class TestGetCommunicationItems:

    def test_get_communication_items(self, mocker, admin_request):
        communication_item = CommunicationItem(name='some name', va_profile_item_id=1)

        mock_get_communication_items = mocker.Mock(return_value=[communication_item])
        mock_communication_item_dao = mocker.Mock(get_communication_items=mock_get_communication_items)
        mocker.patch('app.communication_item.rest.communication_item_dao', new=mock_communication_item_dao)

        response = admin_request.get(
            'communication_item.get_communication_items'
        )

        assert response['data'] == [
            {
                'id': communication_item.id,
                'name': 'some name',
                'va_profile_item_id': 1
            }
        ]
