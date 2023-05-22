import logging
from uuid import UUID


def test_get_communication_items(mocker, admin_request, sample_email_template):
    """
    The fixture "sample_email_template" has the side-effect of creating and
    persisting a CommunicationItem instance that uses the default value for
    default_send_indicator, which is True.
    """

    response = admin_request.get(
        'communication_item.get_communication_items'
    )

    assert isinstance(response["data"], list)

    for communication_item in response["data"]:
        assert isinstance(communication_item, dict)
        assert isinstance(communication_item["default_send_indicator"], bool) and \
            communication_item["default_send_indicator"], "Should be True by default."
        assert isinstance(communication_item["name"], str) and communication_item["name"]
        assert isinstance(communication_item["va_profile_item_id"], int)
        assert isinstance(communication_item["id"], str)

        try:
            assert isinstance(UUID(communication_item["id"]), UUID)
        except ValueError as e:
            logging.exception(e)
            raise
