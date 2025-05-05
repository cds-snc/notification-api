from app.dao.inbound_sms_dao import (
    dao_get_inbound_sms_by_id,
    dao_get_paginated_inbound_sms_for_service_for_public_api,
)


def test_get_inbound_sms_by_id_returns(sample_service, sample_inbound_sms):
    service = sample_service()
    inbound_sms = sample_inbound_sms(service=service)
    inbound_from_db = dao_get_inbound_sms_by_id(inbound_sms.service.id, inbound_sms.id)

    assert inbound_sms == inbound_from_db


def test_dao_get_paginated_inbound_sms_for_service_for_public_api(sample_service, sample_inbound_sms):
    service = sample_service()
    inbound_sms = sample_inbound_sms(service=service)
    inbound_from_db = dao_get_paginated_inbound_sms_for_service_for_public_api(inbound_sms.service.id)

    assert inbound_sms == inbound_from_db[0]


def test_dao_get_paginated_inbound_sms_for_service_for_public_api_return_only_for_service(
    sample_service,
    sample_inbound_sms,
):
    service = sample_service()
    inbound_sms = sample_inbound_sms(service=service)
    another_service = sample_service(service_name='another service')
    another_inbound_sms = sample_inbound_sms(another_service)

    inbound_from_db = dao_get_paginated_inbound_sms_for_service_for_public_api(inbound_sms.service.id)

    assert inbound_sms in inbound_from_db
    assert another_inbound_sms not in inbound_from_db


def test_dao_get_paginated_inbound_sms_for_service_for_public_api_no_inbound_sms_returns_empty_list(sample_service):
    inbound_from_db = dao_get_paginated_inbound_sms_for_service_for_public_api(sample_service().id)

    assert inbound_from_db == []


def test_dao_get_paginated_inbound_sms_for_service_for_public_api_page_size_returns_correct_size(
    sample_service,
    sample_inbound_sms,
):
    service = sample_service()
    inbound_sms_list = [
        sample_inbound_sms(service),
        sample_inbound_sms(service),
        sample_inbound_sms(service),
        sample_inbound_sms(service),
    ]
    reversed_inbound_sms = sorted(inbound_sms_list, key=lambda sms: sms.created_at, reverse=True)

    inbound_from_db = dao_get_paginated_inbound_sms_for_service_for_public_api(
        service.id, older_than=reversed_inbound_sms[1].id, page_size=2
    )

    assert len(inbound_from_db) == 2


def test_dao_get_paginated_inbound_sms_for_service_for_public_api_older_than_returns_correct_list(
    sample_service, sample_inbound_sms
):
    service = sample_service()
    inbound_sms_list = [
        sample_inbound_sms(service),
        sample_inbound_sms(service),
        sample_inbound_sms(service),
        sample_inbound_sms(service),
    ]
    reversed_inbound_sms = sorted(inbound_sms_list, key=lambda sms: sms.created_at, reverse=True)

    inbound_from_db = dao_get_paginated_inbound_sms_for_service_for_public_api(
        service.id, older_than=reversed_inbound_sms[1].id, page_size=2
    )

    expected_inbound_sms = reversed_inbound_sms[2:]

    assert expected_inbound_sms == inbound_from_db


def test_dao_get_paginated_inbound_sms_for_service_for_public_api_older_than_end_returns_empty_list(
    sample_service,
    sample_inbound_sms,
):
    service = sample_service()
    inbound_sms_list = [
        sample_inbound_sms(service),
        sample_inbound_sms(service),
    ]
    reversed_inbound_sms = sorted(inbound_sms_list, key=lambda sms: sms.created_at, reverse=True)

    inbound_from_db = dao_get_paginated_inbound_sms_for_service_for_public_api(
        service.id, older_than=reversed_inbound_sms[1].id, page_size=2
    )

    assert inbound_from_db == []
