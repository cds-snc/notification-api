import uuid


def test_query_id_unknown_uuid(admin_request, sample_user):
    json_resp = admin_request.get("support.query_id", id=uuid.uuid4())
    assert json_resp["type"] == "no result found"


def test_query_id_user(admin_request, sample_user):
    json_resp = admin_request.get("support.query_id", id=sample_user.id)
    assert json_resp["type"] == "user"
    assert json_resp["id"] == str(sample_user.id)
    assert json_resp["name"] == sample_user.name


def test_query_id_service(admin_request, sample_service):
    json_resp = admin_request.get("support.query_id", id=sample_service.id)
    assert json_resp["type"] == "service"
    assert json_resp["id"] == str(sample_service.id)
    assert json_resp["name"] == sample_service.name


def test_query_id_template(admin_request, sample_template):
    json_resp = admin_request.get("support.query_id", id=sample_template.id)
    assert json_resp["type"] == "template"
    assert json_resp["id"] == str(sample_template.id)
    assert json_resp["name"] == sample_template.name
    assert json_resp["service_id"] == str(sample_template.service_id)
    assert json_resp["service_name"] == sample_template.service.name


def test_query_id_job(admin_request, sample_job):
    json_resp = admin_request.get("support.query_id", id=sample_job.id)
    assert json_resp["type"] == "job"
    assert json_resp["id"] == str(sample_job.id)
    assert json_resp["original_file_name"] == sample_job.original_file_name
    # assert json_resp["created_at"] == str(sample_job.created_at)
    assert json_resp["created_by_id"] == str(sample_job.created_by_id)
    assert json_resp["created_by_name"] == sample_job.created_by.name
    # assert json_resp["processing_started"] == str(sample_job.processing_started)
    # assert json_resp["processing_finished"] == str(sample_job.processing_finished)
    assert json_resp["notification_count"] == sample_job.notification_count
    assert json_resp["job_status"] == sample_job.job_status
    assert json_resp["service_id"] == str(sample_job.service_id)
    assert json_resp["service_name"] == sample_job.service.name


def test_query_id_notification(admin_request, sample_notification_with_job):
    json_resp = admin_request.get("support.query_id", id=sample_notification_with_job.id)
    assert json_resp["type"] == "notification"
    assert json_resp["id"] == str(sample_notification_with_job.id)
    assert json_resp["notification_type"] == sample_notification_with_job.notification_type
    assert json_resp["status"] == sample_notification_with_job.status
    # assert json_resp["created_at"] == sample_notification_with_job.created_at
    # assert json_resp["sent_at"] == sample_notification_with_job.sent_at
    assert json_resp["to"] == sample_notification_with_job.to
    assert json_resp["service_id"] == str(sample_notification_with_job.service_id)
    assert json_resp["service_name"] == sample_notification_with_job.service.name
    assert json_resp["job_id"] == str(sample_notification_with_job.job_id)
    assert json_resp["job_row_number"] == sample_notification_with_job.job_row_number
    assert json_resp["api_key_id"] is None
