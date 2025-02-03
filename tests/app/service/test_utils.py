import pytest
from freezegun import freeze_time

from app.dao.date_util import get_current_financial_year_start_year
from app.service.utils import (
    get_gc_organisation_data,
    get_organisation_id_from_crm_org_notes,
)
from tests.conftest import set_config


# see get_financial_year for conversion of financial years.
@freeze_time("2017-03-31 22:59:59.999999")
def test_get_current_financial_year_start_year_before_march():
    current_fy = get_current_financial_year_start_year()
    assert current_fy == 2016


@freeze_time("2017-04-01 4:00:00.000000")
# This test assumes the local timezone is EST
def test_get_current_financial_year_start_year_after_april():
    current_fy = get_current_financial_year_start_year()
    assert current_fy == 2017


@pytest.mark.parametrize(
    "org_notes, expected_id",
    [
        ("en_name_1 > xyz", "id1b"),
        ("fr_name_1 > xyz", "id1b"),
        ("en_name_2 > ", "id2b"),
        ("fr_name_5 > ", None),
        ("en_name_5 > xyz", None),
        ("en_name_3 > xyz", None),
        ("fr_name_3 > ", None),
    ],
)
def test_get_organisation_id_from_crm_org_notes(mocker, org_notes, expected_id):
    mock_gc_org_data = [
        {"id": "id1a", "name_eng": "en_name_1", "name_fra": "fr_name_1", "notify_organisation_id": "id1b"},
        {"id": "id2a", "name_eng": "en_name_2", "name_fra": "fr_name_2", "notify_organisation_id": "id2b"},
        {"id": "id3a", "name_eng": "en_name_3", "name_fra": "fr_name_3", "notify_organisation_id": None},
    ]
    mocker.patch("app.service.utils.get_gc_organisation_data", return_value=mock_gc_org_data)
    assert get_organisation_id_from_crm_org_notes(org_notes) == expected_id


def test_get_gc_org_data(mocker, client):
    with set_config(client.application, "GC_ORGANISATIONS_BUCKET_NAME", None):
        gc_org_fallback_data = get_gc_organisation_data()
        assert len(gc_org_fallback_data) > 0
        assert "Canadian Space Agency" in [x["name_eng"] for x in gc_org_fallback_data]
        assert "Office des transports du Canada" in [x["name_fra"] for x in gc_org_fallback_data]
