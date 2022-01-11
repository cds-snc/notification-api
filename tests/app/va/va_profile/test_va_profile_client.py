import pytest
from requests import RequestException
from requests_mock import ANY

from app.va.va_profile import (
    VAProfileClient,
    NoContactInfoException,
    VAProfileRetryableException,
    VAProfileNonRetryableException
)
from app.models import RecipientIdentifier, SMS_TYPE
from app.va.va_profile.va_profile_client import CommunicationItemNotFoundException

MOCK_VA_PROFILE_URL = 'http://mock.vaprofile.va.gov/'


@pytest.fixture(scope='function')
def test_va_profile_client(mocker):
    mock_logger = mocker.Mock()
    mock_ssl_key_path = 'some_key.pem'
    mock_ssl_cert_path = 'some_cert.pem'
    mock_statsd_client = mocker.Mock()

    test_va_profile_client = VAProfileClient()
    test_va_profile_client.init_app(
        mock_logger,
        MOCK_VA_PROFILE_URL,
        mock_ssl_cert_path,
        mock_ssl_key_path,
        mock_statsd_client
    )

    return test_va_profile_client


def test_get_email_gets_from_correct_url(rmock, test_va_profile_client):
    response = {
        "txAuditId": "0e0e53e0-b1f0-404f-a8e1-cc9ab7ef563e",
        "status": "COMPLETED_SUCCESS",
        "bios": [
            {
                "createDate": "2018-04-17T16:01:13Z",
                "updateDate": "2019-05-09T15:52:33Z",
                "txAuditId": "61fc5389-9ef5-4818-97c8-73f6ff3db396",
                "sourceSystem": "VET360-TEST-PARTNER",
                "sourceDate": "2019-05-09T15:36:34Z",
                "originatingSourceSystem": "EBENEFITS  - CADD",
                "sourceSystemUser": "VAEBENEFITS",
                "effectiveStartDate": "2019-05-09T14:07:10Z",
                "vet360Id": 203,
                "emailId": 121,
                "emailAddressText": "some@email.com"
            }
        ]
    }
    rmock.get(ANY, json=response, status_code=200)

    va_profile_id = '12'
    test_va_profile_client.get_email(va_profile_id)

    assert rmock.called

    expected_url = f"{MOCK_VA_PROFILE_URL}/contact-information-hub/cuf/contact-information/v1/{va_profile_id}/emails"
    assert rmock.request_history[0].url == expected_url


def test_get_email_transforms_from_fhir_format(rmock, test_va_profile_client):
    response = {
        "txAuditId": "0e0e53e0-b1f0-404f-a8e1-cc9ab7ef563e",
        "status": "COMPLETED_SUCCESS",
        "bios": [
            {
                "createDate": "2018-04-17T16:01:13Z",
                "updateDate": "2019-05-09T15:52:33Z",
                "txAuditId": "61fc5389-9ef5-4818-97c8-73f6ff3db396",
                "sourceSystem": "VET360-TEST-PARTNER",
                "sourceDate": "2019-05-09T15:36:34Z",
                "originatingSourceSystem": "EBENEFITS  - CADD",
                "sourceSystemUser": "VAEBENEFITS",
                "effectiveStartDate": "2019-05-09T14:07:10Z",
                "vet360Id": 203,
                "emailId": 121,
                "emailAddressText": "some@email.com"
            }
        ]
    }
    rmock.get(ANY, json=response, status_code=200)

    test_va_profile_client.get_email('301^PI^200VETS^USDVA')

    assert rmock.called

    expected_url = f"{MOCK_VA_PROFILE_URL}/contact-information-hub/cuf/contact-information/v1/301/emails"
    assert rmock.request_history[0].url == expected_url


def test_get_telephone_gets_from_correct_url(rmock, test_va_profile_client):
    response = {
        "txAuditId": "0e0e53e0-b1f0-404f-a8e1-cc9ab7ef563e",
        "status": "COMPLETED_SUCCESS",
        "bios": [
            {
                "createDate": "2019-10-25T13:07:50Z",
                "updateDate": "2020-11-25T15:30:23Z",
                "txAuditId": "f9f28afb-2ac3-4f92-acef-5f36f1fbd322",
                "sourceSystem": "VAPROFILE-TEST-PARTNER",
                "sourceDate": "2020-11-25T14:38:17Z",
                "originatingSourceSystem": "eVA",
                "sourceSystemUser": "foo",
                "effectiveStartDate": "2020-11-25T14:38:17Z",
                "effectiveEndDate": "2021-11-25T14:38:17Z",
                "confirmationDate": "2020-11-25T14:38:17Z",
                "vet360Id": 2004,
                "telephoneId": 14365,
                "internationalIndicator": False,
                "phoneType": "MOBILE",
                "countryCode": "1",
                "areaCode": "555",
                "phoneNumber": "1111111",
                "connectionStatusCode": "NO_KNOWN_PROBLEM"
            }
        ]
    }
    rmock.get(ANY, json=response, status_code=200)

    va_profile_id = '12'
    test_va_profile_client.get_telephone(va_profile_id)

    assert rmock.called

    expected_url =\
        f"{MOCK_VA_PROFILE_URL}/contact-information-hub/cuf/contact-information/v1/{va_profile_id}/telephones"
    assert rmock.request_history[0].url == expected_url


def test_get_email_gets_single_email(rmock, test_va_profile_client):
    expected_email = 'hello@moto.com'
    response = {
        "txAuditId": "0e0e53e0-b1f0-404f-a8e1-cc9ab7ef563e",
        "status": "COMPLETED_SUCCESS",
        "bios": [
            {
                "createDate": "2018-04-17T16:01:13Z",
                "updateDate": "2019-05-09T15:52:33Z",
                "txAuditId": "61fc5389-9ef5-4818-97c8-73f6ff3db396",
                "sourceSystem": "VET360-TEST-PARTNER",
                "sourceDate": "2019-05-09T15:36:34Z",
                "originatingSourceSystem": "EBENEFITS  - CADD",
                "sourceSystemUser": "VAEBENEFITS",
                "effectiveStartDate": "2019-05-09T14:07:10Z",
                "vet360Id": 203,
                "emailId": 121,
                "emailAddressText": expected_email
            }
        ]
    }
    rmock.get(ANY, json=response, status_code=200)

    actual_email = test_va_profile_client.get_email('1')
    assert actual_email == expected_email


def test_get_telephone_gets_single_mobile_phone_number(rmock, test_va_profile_client):
    expected_phone_number = '+15551111111'
    response = {
        "txAuditId": "0e0e53e0-b1f0-404f-a8e1-cc9ab7ef563e",
        "status": "COMPLETED_SUCCESS",
        "bios": [
            {
                "createDate": "2019-10-25T13:07:50Z",
                "updateDate": "2020-11-25T15:30:23Z",
                "txAuditId": "f9f28afb-2ac3-4f92-acef-5f36f1fbd322",
                "sourceSystem": "VAPROFILE-TEST-PARTNER",
                "sourceDate": "2020-11-25T14:38:17Z",
                "originatingSourceSystem": "eVA",
                "sourceSystemUser": "foo",
                "effectiveStartDate": "2020-11-25T14:38:17Z",
                "effectiveEndDate": "2021-11-25T14:38:17Z",
                "confirmationDate": "2020-11-25T14:38:17Z",
                "vet360Id": 2004,
                "telephoneId": 14365,
                "internationalIndicator": False,
                "phoneType": "MOBILE",
                "countryCode": "1",
                "areaCode": "555",
                "phoneNumber": "1111111",
                "connectionStatusCode": "NO_KNOWN_PROBLEM"
            }
        ]
    }
    rmock.get(ANY, json=response, status_code=200)

    actual_phone_number = test_va_profile_client.get_telephone('1')
    assert actual_phone_number == expected_phone_number


def test_get_telephone_no_bio(rmock, test_va_profile_client):
    response = {
        "messages": [
            {
                "code": "CORE103",
                "key": "_CUF_NOT_FOUND",
                "text": "The TelephoneBio for id/criteria mdm.cuf.contact.information.bio.TelephoneBio@69633ebb"
                        "[telephoneId=<null>,internationalIndicator=<null>,phoneType=<null>,countryCode=<null>,"
                        "areaCode=<null>,phoneNumber=<null>,phoneNumberExt=<null>,connectionStatusCode=<null>,"
                        "textMessageCapableInd=<null>,textMessagePermInd=<null>,voiceMailAcceptableInd=<null>,"
                        "ttyInd=<null>,effectiveStartDate=<null>,effectiveEndDate=<null>,confirmationDate=<null>,"
                        "vet360Id=<null>,vaProfileId=8477,createDate=<null>,updateDate=<null>,txAuditId=<null>,"
                        "sourceSystem=<null>,sourceDate=<null>,originatingSourceSystem=<null>,"
                        "sourceSystemUser=<null>] could not be found. Please correct your request and try again!",
                "severity": "INFO"
            }
        ],
        "txAuditId": "5fa04ebc-2aeb-42c7-acec-4b2046f88cf4",
        "status": "COMPLETED_SUCCESS"
    }
    rmock.get(ANY, json=response, status_code=200)

    with pytest.raises(NoContactInfoException):
        test_va_profile_client.get_telephone('1')


def test_get_telephone_gets_single_work_phone_number(rmock, test_va_profile_client):
    response = {
        "txAuditId": "0e0e53e0-b1f0-404f-a8e1-cc9ab7ef563e",
        "status": "COMPLETED_SUCCESS",
        "bios": [
            {
                "createDate": "2019-10-25T13:07:50Z",
                "updateDate": "2020-11-25T15:30:23Z",
                "txAuditId": "f9f28afb-2ac3-4f92-acef-5f36f1fbd322",
                "sourceSystem": "VAPROFILE-TEST-PARTNER",
                "sourceDate": "2020-11-25T14:38:17Z",
                "originatingSourceSystem": "eVA",
                "sourceSystemUser": "foo",
                "effectiveStartDate": "2020-11-25T14:38:17Z",
                "effectiveEndDate": "2021-11-25T14:38:17Z",
                "confirmationDate": "2020-11-25T14:38:17Z",
                "vet360Id": 2004,
                "telephoneId": 14365,
                "internationalIndicator": False,
                "phoneType": "WORK",
                "countryCode": "1",
                "areaCode": "555",
                "phoneNumber": "1111111",
                "connectionStatusCode": "NO_KNOWN_PROBLEM"
            }
        ]
    }
    rmock.get(ANY, json=response, status_code=200)

    with pytest.raises(NoContactInfoException):
        test_va_profile_client.get_telephone('1')


def test_get_telephone_gets_single_home_phone_number(rmock, test_va_profile_client):
    expected_phone_number = '+15551111111'
    response = {
        "txAuditId": "0e0e53e0-b1f0-404f-a8e1-cc9ab7ef563e",
        "status": "COMPLETED_SUCCESS",
        "bios": [
            {
                "createDate": "2019-10-25T13:07:50Z",
                "updateDate": "2020-11-25T15:30:23Z",
                "txAuditId": "f9f28afb-2ac3-4f92-acef-5f36f1fbd322",
                "sourceSystem": "VAPROFILE-TEST-PARTNER",
                "sourceDate": "2020-11-25T14:38:17Z",
                "originatingSourceSystem": "eVA",
                "sourceSystemUser": "foo",
                "effectiveStartDate": "2020-11-25T14:38:17Z",
                "effectiveEndDate": "2021-11-25T14:38:17Z",
                "confirmationDate": "2020-11-25T14:38:17Z",
                "vet360Id": 2004,
                "telephoneId": 14365,
                "internationalIndicator": False,
                "phoneType": "HOME",
                "countryCode": "1",
                "areaCode": "555",
                "phoneNumber": "1111111",
                "connectionStatusCode": "NO_KNOWN_PROBLEM"
            }
        ]
    }
    rmock.get(ANY, json=response, status_code=200)

    actual_phone_number = test_va_profile_client.get_telephone('1')
    assert actual_phone_number == expected_phone_number


def test_get_telephone_gets_multiple_home_phone_numbers(rmock, test_va_profile_client):
    expected_phone_number = '+15551111111'
    response = {
        "txAuditId": "0e0e53e0-b1f0-404f-a8e1-cc9ab7ef563e",
        "status": "COMPLETED_SUCCESS",
        "bios": [
            {
                "createDate": "2019-10-26T13:07:50Z",
                "updateDate": "2020-11-25T15:30:23Z",
                "txAuditId": "f9f28afb-2ac3-4f92-acef-5f36f1fbd322",
                "sourceSystem": "VAPROFILE-TEST-PARTNER",
                "sourceDate": "2020-11-25T14:38:17Z",
                "originatingSourceSystem": "eVA",
                "sourceSystemUser": "foo",
                "effectiveStartDate": "2020-11-25T14:38:17Z",
                "effectiveEndDate": "2021-11-25T14:38:17Z",
                "confirmationDate": "2020-11-25T14:38:17Z",
                "vet360Id": 2004,
                "telephoneId": 14365,
                "internationalIndicator": False,
                "phoneType": "HOME",
                "countryCode": "1",
                "areaCode": "555",
                "phoneNumber": "1111111",
                "connectionStatusCode": "NO_KNOWN_PROBLEM"
            },
            {
                "createDate": "2019-09-25T13:07:50Z",
                "updateDate": "2020-10-25T15:30:23Z",
                "txAuditId": "f9f28afb-2ac3-4f92-acef-5f36f1fbd322",
                "sourceSystem": "VAPROFILE-TEST-PARTNER",
                "sourceDate": "2020-11-25T14:38:17Z",
                "originatingSourceSystem": "eVA",
                "sourceSystemUser": "foo",
                "effectiveStartDate": "2020-11-25T14:38:17Z",
                "effectiveEndDate": "2021-11-25T14:38:17Z",
                "confirmationDate": "2020-11-25T14:38:17Z",
                "vet360Id": 2004,
                "telephoneId": 14365,
                "internationalIndicator": False,
                "phoneType": "HOME",
                "countryCode": "1",
                "areaCode": "555",
                "phoneNumber": "2222222",
                "connectionStatusCode": "NO_KNOWN_PROBLEM"
            }
        ]
    }
    rmock.get(ANY, json=response, status_code=200)

    actual_phone_number = test_va_profile_client.get_telephone('1')
    assert actual_phone_number == expected_phone_number


def test_get_telephone_gets_multiple_mobile_phone_numbers(rmock, test_va_profile_client):
    expected_phone_number = '+15551111111'
    response = {
        "txAuditId": "0e0e53e0-b1f0-404f-a8e1-cc9ab7ef563e",
        "status": "COMPLETED_SUCCESS",
        "bios": [
            {
                "createDate": "2019-10-25T13:07:50Z",
                "updateDate": "2020-11-25T15:30:23Z",
                "txAuditId": "f9f28afb-2ac3-4f92-acef-5f36f1fbd322",
                "sourceSystem": "VAPROFILE-TEST-PARTNER",
                "sourceDate": "2020-11-25T14:38:17Z",
                "originatingSourceSystem": "eVA",
                "sourceSystemUser": "foo",
                "effectiveStartDate": "2020-11-25T14:38:17Z",
                "effectiveEndDate": "2021-11-25T14:38:17Z",
                "confirmationDate": "2020-11-25T14:38:17Z",
                "vet360Id": 2004,
                "telephoneId": 14365,
                "internationalIndicator": False,
                "phoneType": "MOBILE",
                "countryCode": "1",
                "areaCode": "555",
                "phoneNumber": "1111111",
                "connectionStatusCode": "NO_KNOWN_PROBLEM"
            },
            {
                "createDate": "2019-10-23T13:07:50Z",
                "updateDate": "2020-11-25T15:30:23Z",
                "txAuditId": "f9f28afb-2ac3-4f92-acef-5f36f1fbd322",
                "sourceSystem": "VAPROFILE-TEST-PARTNER",
                "sourceDate": "2020-11-25T14:38:17Z",
                "originatingSourceSystem": "eVA",
                "sourceSystemUser": "foo",
                "effectiveStartDate": "2020-11-25T14:38:17Z",
                "effectiveEndDate": "2021-11-25T14:38:17Z",
                "confirmationDate": "2020-11-25T14:38:17Z",
                "vet360Id": 2004,
                "telephoneId": 14365,
                "internationalIndicator": False,
                "phoneType": "MOBILE",
                "countryCode": "1",
                "areaCode": "555",
                "phoneNumber": "2222222",
                "connectionStatusCode": "NO_KNOWN_PROBLEM"
            }
        ]
    }
    rmock.get(ANY, json=response, status_code=200)

    actual_phone_number = test_va_profile_client.get_telephone('1')
    assert actual_phone_number == expected_phone_number


def test_get_telephone_gets_mobile_phone_number(rmock, test_va_profile_client):
    expected_phone_number = '+15551111111'
    response = {
        "txAuditId": "0e0e53e0-b1f0-404f-a8e1-cc9ab7ef563e",
        "status": "COMPLETED_SUCCESS",
        "bios": [
            {
                "createDate": "2020-10-23T13:07:50Z",
                "updateDate": "2020-11-25T15:30:23Z",
                "txAuditId": "f9f28afb-2ac3-4f92-acef-5f36f1fbd322",
                "sourceSystem": "VAPROFILE-TEST-PARTNER",
                "sourceDate": "2020-11-25T14:38:17Z",
                "originatingSourceSystem": "eVA",
                "sourceSystemUser": "foo",
                "effectiveStartDate": "2020-11-25T14:38:17Z",
                "effectiveEndDate": "2021-11-25T14:38:17Z",
                "confirmationDate": "2020-11-25T14:38:17Z",
                "vet360Id": 2004,
                "telephoneId": 14365,
                "internationalIndicator": False,
                "phoneType": "HOME",
                "countryCode": "1",
                "areaCode": "555",
                "phoneNumber": "2222222",
                "connectionStatusCode": "NO_KNOWN_PROBLEM"
            },
            {
                "createDate": "2019-10-25T13:07:50Z",
                "updateDate": "2019-11-25T15:30:23Z",
                "txAuditId": "f9f28afb-2ac3-4f92-acef-5f36f1fbd322",
                "sourceSystem": "VAPROFILE-TEST-PARTNER",
                "sourceDate": "2020-11-25T14:38:17Z",
                "originatingSourceSystem": "eVA",
                "sourceSystemUser": "foo",
                "effectiveStartDate": "2020-11-25T14:38:17Z",
                "effectiveEndDate": "2021-11-25T14:38:17Z",
                "confirmationDate": "2020-11-25T14:38:17Z",
                "vet360Id": 2004,
                "telephoneId": 14365,
                "internationalIndicator": False,
                "phoneType": "HOME",
                "countryCode": "1",
                "areaCode": "555",
                "phoneNumber": "333",
                "connectionStatusCode": "NO_KNOWN_PROBLEM"
            },
            {
                "createDate": "2019-10-25T13:07:50Z",
                "updateDate": "2019-11-25T15:30:23Z",
                "txAuditId": "f9f28afb-2ac3-4f92-acef-5f36f1fbd322",
                "sourceSystem": "VAPROFILE-TEST-PARTNER",
                "sourceDate": "2020-11-25T14:38:17Z",
                "originatingSourceSystem": "eVA",
                "sourceSystemUser": "foo",
                "effectiveStartDate": "2020-11-25T14:38:17Z",
                "effectiveEndDate": "2021-11-25T14:38:17Z",
                "confirmationDate": "2020-11-25T14:38:17Z",
                "vet360Id": 2004,
                "telephoneId": 14365,
                "internationalIndicator": False,
                "phoneType": "MOBILE",
                "countryCode": "1",
                "areaCode": "555",
                "phoneNumber": "1111111",
                "connectionStatusCode": "NO_KNOWN_PROBLEM"
            }
        ]
    }
    rmock.get(ANY, json=response, status_code=200)

    actual_phone_number = test_va_profile_client.get_telephone('1')
    assert actual_phone_number == expected_phone_number


def test_get_email_gets_most_recently_created_email(notify_api, rmock, test_va_profile_client):
    older_email = 'older@moto.com'
    newer_email = 'newer@moto.com'

    response = {
        "txAuditId": "0e0e53e0-b1f0-404f-a8e1-cc9ab7ef563e",
        "status": "COMPLETED_SUCCESS",
        "bios": [
            {
                "createDate": "2018-04-17T16:01:13Z",
                "updateDate": "2019-05-09T15:52:33Z",
                "txAuditId": "61fc5389-9ef5-4818-97c8-73f6ff3db396",
                "sourceSystem": "VET360-TEST-PARTNER",
                "sourceDate": "2019-05-09T15:36:34Z",
                "originatingSourceSystem": "EBENEFITS  - CADD",
                "sourceSystemUser": "VAEBENEFITS",
                "effectiveStartDate": "2019-05-09T14:07:10Z",
                "vet360Id": 203,
                "emailId": 121,
                "emailAddressText": older_email
            },
            {
                "createDate": "2020-04-17T16:01:13Z",
                "updateDate": "2020-05-09T15:52:33Z",
                "txAuditId": "61fc5389-9ef5-4818-97c8-73f6ff3db396",
                "sourceSystem": "VET360-TEST-PARTNER",
                "sourceDate": "2020-05-09T15:36:34Z",
                "originatingSourceSystem": "EBENEFITS  - CADD",
                "sourceSystemUser": "VAEBENEFITS",
                "effectiveStartDate": "2020-05-09T14:07:10Z",
                "vet360Id": 203,
                "emailId": 121,
                "emailAddressText": newer_email
            }
        ]
    }
    rmock.get(ANY, json=response, status_code=200)

    actual_email = test_va_profile_client.get_email('1')
    assert actual_email == newer_email


def test_get_email_raises_exception_when_no_email_bio(notify_api, rmock, test_va_profile_client):
    response = {
        "messages": [
            {
                "code": "CORE103",
                "key": "_CUF_NOT_FOUND",
                "text": "The EmailBio for id/criteria mdm.cuf.",
                "severity": "INFO"
            }
        ],
        "txAuditId": "dca32cae-b410-46c5-b61b-9a382567843f",
        "status": "COMPLETED_SUCCESS"
    }
    rmock.get(ANY, json=response, status_code=200)

    with pytest.raises(NoContactInfoException):
        test_va_profile_client.get_email('1')


def test_get_email_raises_exception_when_failed_request(notify_api, rmock, test_va_profile_client):
    response = {
        "messages": [
            {
                "code": "CORE103",
                "key": "_CUF_NOT_FOUND",
                "text": "The ContactInformationBio for id/criteria 103 could not be found. Please correct your requ...",
                "severity": "INFO"
            }
        ],
        "txAuditId": "dca32cae-b410-46c5-b61b-9a382567843f",
        "status": "COMPLETED_FAILURE"
    }
    rmock.get(ANY, json=response, status_code=200)

    with pytest.raises(VAProfileNonRetryableException):
        test_va_profile_client.get_email('1')


@pytest.mark.parametrize(
    "status",
    [429, 500]
)
def test_get_email_raises_retryable_exception(notify_api, rmock, test_va_profile_client, status):
    rmock.get(ANY, status_code=status)

    with pytest.raises(VAProfileRetryableException):
        test_va_profile_client.get_email('1')


@pytest.mark.parametrize(
    "status",
    [400, 403, 404]
)
def test_get_email_raises_non_retryable_exception(notify_api, rmock, test_va_profile_client, status):
    rmock.get(ANY, status_code=status)

    with pytest.raises(VAProfileNonRetryableException):
        test_va_profile_client.get_email('1')


def test_should_throw_va_retryable_exception_when_request_exception_is_thrown(
        test_va_profile_client, mocker):
    mocker.patch('app.va.va_profile.va_profile_client.requests.get', side_effect=RequestException)

    with pytest.raises(VAProfileRetryableException) as e:
        test_va_profile_client.get_email('1')

        assert (
            e.value.failure_reason
            == 'VA Profile returned RequestException while querying for VA Profile ID'
        )


class TestCommunicationPermissions:

    def test_get_is_communication_allowed_should_throw_exception_if_communication_item_does_not_exist_on_user(
            self, test_va_profile_client, rmock
    ):
        response = {
            "txAuditId": "b8c82dd0-65d9-4e50-bd3e-cd83a4844ff0",
            "status": "COMPLETED_SUCCESS",
            "bios": []
        }
        rmock.get(ANY, json=response, status_code=200)

        recipient_identifier = RecipientIdentifier(id_type='VAPROFILEID', id_value='1')

        with pytest.raises(CommunicationItemNotFoundException):
            test_va_profile_client.get_is_communication_allowed(
                recipient_identifier, 'some-id', 'some-notification-id', SMS_TYPE
            )

    def test_get_is_communication_allowed_should_return_false_if_communication_item_is_not_allowed_on_user(
            self, test_va_profile_client, rmock
    ):
        response = {
            "txAuditId": "b8c82dd0-65d9-4e50-bd3e-cd83a4844ff0",
            "status": "COMPLETED_SUCCESS",
            "bios": [
                {
                    "createDate": "2021-08-02T17:22:27Z",
                    "updateDate": "2021-08-02T17:22:27Z",
                    "txAuditId": "59bde0dc-a9c1-4066-bec1-f54ad1282b33",
                    "sourceSystem": "VAPROFILE-TEST-PARTNER",
                    "sourceDate": "2021-08-02T17:11:16Z",
                    "originatingSourceSystem": "release testing",
                    "sourceSystemUser": "Dwight Snoot",
                    "communicationPermissionId": 1,
                    "vaProfileId": 1,
                    "communicationChannelId": 1,
                    "communicationItemId": 'some-valid-id',
                    "communicationChannelName": "Text",
                    "communicationItemCommonName": "Board of Veterans' Appeals hearing reminder",
                    "allowed": False,
                    "confirmationDate": "2021-08-02T17:11:16Z"
                }
            ]
        }
        rmock.get(ANY, json=response, status_code=200)

        recipient_identifier = RecipientIdentifier(id_type='VAPROFILEID', id_value='1')

        assert not test_va_profile_client.get_is_communication_allowed(
            recipient_identifier, 'some-valid-id', 'some-notification-id', SMS_TYPE
        )

    def test_get_is_communication_allowed_should_return_false_if_communication_item_channel_is_not_of_notification_type(
            self, test_va_profile_client, rmock
    ):
        response = {
            "txAuditId": "b8c82dd0-65d9-4e50-bd3e-cd83a4844ff0",
            "status": "COMPLETED_SUCCESS",
            "bios": [
                {
                    "createDate": "2021-08-02T17:22:27Z",
                    "updateDate": "2021-08-02T17:22:27Z",
                    "txAuditId": "59bde0dc-a9c1-4066-bec1-f54ad1282b33",
                    "sourceSystem": "VAPROFILE-TEST-PARTNER",
                    "sourceDate": "2021-08-02T17:11:16Z",
                    "originatingSourceSystem": "release testing",
                    "sourceSystemUser": "Dwight Snoot",
                    "communicationPermissionId": 1,
                    "vaProfileId": 1,
                    "communicationChannelId": 1,
                    "communicationItemId": 'some-valid-id',
                    "communicationChannelName": "Email",
                    "communicationItemCommonName": "Board of Veterans' Appeals hearing reminder",
                    "allowed": False,
                    "confirmationDate": "2021-08-02T17:11:16Z"
                }
            ]
        }
        rmock.get(ANY, json=response, status_code=200)

        recipient_identifier = RecipientIdentifier(id_type='VAPROFILEID', id_value='1')

        with pytest.raises(CommunicationItemNotFoundException):
            test_va_profile_client.get_is_communication_allowed(
                recipient_identifier, 'some-valid-id', 'some-notification-id', SMS_TYPE
            )

    def test_get_is_communication_allowed_should_raise_exception_if_recipient_has_no_permissions(
            self, test_va_profile_client, rmock
    ):
        # TODO: Note that this behavior will change once we starting using default communication item permissions
        response = {
            "messages": [
                {
                    "code": "CP310",
                    "key": "PermissionNotFound",
                    "text": "Permission not found for vaProfileId 1",
                    "severity": "ERROR"
                }
            ],
            "txAuditId": "37df9590-e791-4392-ae77-eaffc782276c",
            "status": "COMPLETED_SUCCESS"
        }
        rmock.get(ANY, json=response, status_code=200)

        recipient_identifier = RecipientIdentifier(id_type='VAPROFILEID', id_value='1')

        with pytest.raises(CommunicationItemNotFoundException):
            test_va_profile_client.get_is_communication_allowed(
                recipient_identifier, 'some-random-id', 'some-notification-id', SMS_TYPE
            )

    def test_get_is_communication_allowed_should_return_true_if_user_allows_communication_item(
            self, test_va_profile_client, rmock
    ):
        response = {
            "txAuditId": "b8c82dd0-65d9-4e50-bd3e-cd83a4844ff0",
            "status": "COMPLETED_SUCCESS",
            "bios": [
                {
                    "createDate": "2021-08-02T17:22:27Z",
                    "updateDate": "2021-08-02T17:22:27Z",
                    "txAuditId": "59bde0dc-a9c1-4066-bec1-f54ad1282b33",
                    "sourceSystem": "VAPROFILE-TEST-PARTNER",
                    "sourceDate": "2021-08-02T17:11:16Z",
                    "originatingSourceSystem": "release testing",
                    "sourceSystemUser": "Dwight Snoot",
                    "communicationPermissionId": 2481,
                    "vaProfileId": 1,
                    "communicationChannelId": 1,
                    "communicationItemId": 1,
                    "communicationChannelName": "Text",
                    "communicationItemCommonName": "Board of Veterans' Appeals hearing reminder",
                    "allowed": True,
                    "confirmationDate": "2021-08-02T17:11:16Z"
                },
                {
                    "createDate": "2021-08-02T17:23:30Z",
                    "updateDate": "2021-08-02T17:23:30Z",
                    "txAuditId": "fe7cf35a-ab2a-4ce0-ad8b-7514a391d94f",
                    "sourceSystem": "VAPROFILE-TEST-PARTNER",
                    "sourceDate": "2021-08-02T17:11:16Z",
                    "originatingSourceSystem": "release testing",
                    "sourceSystemUser": "Dwight Snoot",
                    "communicationPermissionId": 2482,
                    "vaProfileId": 1,
                    "communicationChannelId": 2,
                    "communicationItemId": 2,
                    "communicationChannelName": "Email",
                    "communicationItemCommonName": "COVID-19 Updates",
                    "allowed": True,
                    "confirmationDate": "2021-08-02T17:11:16Z"
                },
                {
                    "createDate": "2021-07-28T20:00:12Z",
                    "updateDate": "2021-07-28T20:00:12Z",
                    "txAuditId": "01941ff7-8f0c-4713-87ca-8cd4df1a1c46",
                    "sourceSystem": "VAPROFILE-TEST-PARTNER",
                    "sourceDate": "2021-07-28T19:58:47Z",
                    "communicationPermissionId": 2101,
                    "vaProfileId": 1,
                    "communicationChannelId": 1,
                    "communicationItemId": 'some-valid-id',
                    "communicationChannelName": "Text",
                    "communicationItemCommonName": "Appointment reminders",
                    "allowed": True
                }
            ]
        }
        rmock.get(ANY, json=response, status_code=200)

        recipient_identifier = RecipientIdentifier(id_type='VAPROFILEID', id_value='1')

        assert test_va_profile_client.get_is_communication_allowed(
            recipient_identifier, 'some-valid-id', 'some-notification-id', SMS_TYPE
        )
