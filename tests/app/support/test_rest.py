import json
import uuid
from datetime import date, datetime, timedelta
from functools import partial
from unittest.mock import ANY, call

import pytest
import pytest_mock
from flask import Flask, current_app, url_for
from freezegun import freeze_time
from notifications_utils.clients.redis import (
    daily_limit_cache_key,
    near_daily_limit_cache_key,
    over_daily_limit_cache_key,
)

from app.dao.organisation_dao import dao_add_service_to_organisation
from app.dao.service_sms_sender_dao import dao_get_sms_senders_by_service_id
from app.dao.service_user_dao import dao_get_service_user
from app.dao.services_dao import dao_remove_user_from_service
from app.dao.templates_dao import dao_redact_template
from app.dao.users_dao import save_model_user
from app.dbsetup import RoutingSQLAlchemy
from app.models import (
    EMAIL_TYPE,
    INBOUND_SMS_TYPE,
    INTERNATIONAL_SMS_TYPE,
    KEY_TYPE_NORMAL,
    KEY_TYPE_TEAM,
    KEY_TYPE_TEST,
    LETTER_TYPE,
    SMS_TYPE,
    EmailBranding,
    InboundNumber,
    Notification,
    Service,
    ServiceEmailReplyTo,
    ServiceLetterContact,
    ServicePermission,
    ServiceSmsSender,
    User,
)
from tests import create_authorization_header
from tests.app.conftest import sample_notification as create_sample_notification
from tests.app.conftest import sample_notification_with_job
from tests.app.conftest import (
    sample_user_service_permission as create_user_service_permission,
)


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
    assert json_resp["api_key_id"] == None
