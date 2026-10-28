import importlib
from datetime import datetime, timedelta

from alembic.migration import MigrationContext
from alembic.operations import Operations
from freezegun import freeze_time

from app import db
from app.models import Notification, ScheduledNotification
from tests.app.db import (
    create_notification,
    create_scheduled_one_off_notification,
    save_scheduled_notification,
)

migration = importlib.import_module("migrations.versions.0527_sched_notifs_move_rows")


def _run_upgrade():
    db.session.commit()
    with db.engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
    db.session.expire_all()


def _legacy(template, scheduled_for, **kwargs):
    return save_scheduled_notification(
        create_notification(template=template, **kwargs), scheduled_for=scheduled_for.strftime("%Y-%m-%d %H:%M")
    )


def test_moves_pending_legacy_rows_out_of_the_notifications_table(sample_template_with_placeholders, sample_api_key):
    scheduled_for = datetime.utcnow() + timedelta(days=1)
    with freeze_time("2026-10-27 09:00"):
        notification = _legacy(
            sample_template_with_placeholders,
            scheduled_for,
            personalisation={"name": "Jo"},
            api_key=sample_api_key,
            key_type=sample_api_key.key_type,
            client_reference="my-ref",
            billable_units=2,
        )
    expected = {
        "notification_id": notification.id,
        "service_id": notification.service_id,
        "template_id": notification.template_id,
        "template_version": notification.template_version,
        "notification_type": notification.notification_type,
        "to": notification.to,
    }

    _run_upgrade()

    assert Notification.query.count() == 0
    scheduled_notification = ScheduledNotification.query.one()
    assert {key: getattr(scheduled_notification, key) for key in expected} == expected
    assert scheduled_notification.personalisation == {"name": "Jo"}
    assert scheduled_notification.api_key_id == sample_api_key.id
    assert scheduled_notification.key_type == sample_api_key.key_type
    assert scheduled_notification.client_reference == "my-ref"
    assert scheduled_notification.billable_units == 2
    assert scheduled_notification.created_at == datetime(2026, 10, 27, 9, 0)
    assert scheduled_notification.scheduled_for == scheduled_for.replace(second=0, microsecond=0)


def test_leaves_legacy_rows_that_are_due_soon(sample_template):
    notification = _legacy(sample_template, datetime.utcnow() + timedelta(minutes=5))

    _run_upgrade()

    assert Notification.query.one().id == notification.id
    assert ScheduledNotification.query.one().service_id is None


def test_deletes_legacy_rows_that_cant_be_sent(sample_template):
    later = datetime.utcnow() + timedelta(days=1)
    already_processed = _legacy(sample_template, later)
    already_processed.scheduled_notification.pending = False
    not_created = _legacy(sample_template, later, status="sending")
    not_created.scheduled_notification.pending = True

    _run_upgrade()

    assert ScheduledNotification.query.count() == 0
    assert {n.id for n in Notification.query.all()} == {already_processed.id, not_created.id}


def test_leaves_rows_in_the_new_format(sample_template):
    scheduled_notification = create_scheduled_one_off_notification(sample_template, personalisation={"name": "Jo"})

    _run_upgrade()

    assert ScheduledNotification.query.one().id == scheduled_notification.id
    assert ScheduledNotification.query.one().personalisation == {"name": "Jo"}
