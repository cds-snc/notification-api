import uuid

import pytest


def test_find_ids_user(admin_request, sample_user):
    json_resp = admin_request.get("support.find_ids", ids=sample_user.id)[0]
    assert json_resp["type"] == "user"
    assert json_resp["id"] == str(sample_user.id)
    assert json_resp["user_name"] == sample_user.name


def test_find_ids_service(admin_request, sample_service):
    json_resp = admin_request.get("support.find_ids", ids=sample_service.id)[0]
    assert json_resp["type"] == "service"
    assert json_resp["id"] == str(sample_service.id)
    assert json_resp["service_name"] == sample_service.name


def test_find_ids_template(admin_request, sample_template):
    json_resp = admin_request.get("support.find_ids", ids=sample_template.id)[0]
    assert json_resp["type"] == "template"
    assert json_resp["id"] == str(sample_template.id)
    assert json_resp["template_name"] == sample_template.name
    assert json_resp["service_id"] == str(sample_template.service_id)
    assert json_resp["service_name"] == sample_template.service.name


def test_find_ids_job(admin_request, sample_job):
    json_resp = admin_request.get("support.find_ids", ids=sample_job.id)[0]
    assert json_resp["type"] == "job"
    assert json_resp["id"] == str(sample_job.id)
    assert json_resp["original_file_name"] == sample_job.original_file_name
    assert json_resp["created_by_id"] == str(sample_job.created_by_id)
    assert json_resp["created_by_name"] == sample_job.created_by.name
    assert json_resp["notification_count"] == sample_job.notification_count
    assert json_resp["job_status"] == sample_job.job_status
    assert json_resp["service_id"] == str(sample_job.service_id)
    assert json_resp["service_name"] == sample_job.service.name
    assert json_resp["template_id"] == str(sample_job.template_id)
    assert json_resp["template_name"] == sample_job.template.name


def test_find_ids_notification(admin_request, sample_notification_with_job):
    json_resp = admin_request.get("support.find_ids", ids=sample_notification_with_job.id)[0]
    assert json_resp["type"] == "notification"
    assert json_resp["id"] == str(sample_notification_with_job.id)
    assert json_resp["notification_type"] == sample_notification_with_job.notification_type
    assert json_resp["status"] == sample_notification_with_job.status
    assert json_resp["to"] == sample_notification_with_job.to
    assert json_resp["service_id"] == str(sample_notification_with_job.service_id)
    assert json_resp["service_name"] == sample_notification_with_job.service.name
    assert json_resp["template_id"] == str(sample_notification_with_job.template_id)
    assert json_resp["template_name"] == sample_notification_with_job.template.name
    assert json_resp["job_id"] == str(sample_notification_with_job.job_id)
    assert json_resp["job_row_number"] == sample_notification_with_job.job_row_number
    assert json_resp["api_key_id"] is None


def test_find_ids_unknown_uuid(admin_request, sample_user):
    search_uuid = str(uuid.uuid4())
    json_resp = admin_request.get("support.find_ids", ids=search_uuid)[0]
    assert json_resp["type"] == "no result found"


def test_find_ids_no_ids(admin_request):
    json_resp = admin_request.get("support.find_ids", _expected_status=400, ids=None)
    assert json_resp == {"error": "no ids provided"}


def test_find_ids_empty_ids(admin_request):
    json_resp = admin_request.get("support.find_ids", _expected_status=400, ids=[])
    assert json_resp == {"error": "no ids provided"}


def test_find_ids_id_not_uuid(admin_request):
    search_uuid = "hello"
    json_resp = admin_request.get("support.find_ids", ids=search_uuid)[0]
    assert json_resp["type"] == "not a uuid"


@pytest.mark.parametrize("delimiter", [",", " ", "  ,\n\n, "])
def test_find_ids_two_ids(admin_request, sample_user, sample_service, delimiter):
    json_resp = admin_request.get("support.find_ids", ids=f"{sample_user.id}{delimiter}{sample_service.id}")
    assert len(json_resp) == 2
    assert json_resp[0]["type"] == "user"
    assert json_resp[1]["type"] == "service"
