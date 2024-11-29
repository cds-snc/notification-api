from collections import namedtuple
from datetime import datetime

import pytest

from app.dao.annual_limits_data_dao import (
    fetch_quarter_cummulative_stats,
    get_previous_quarter,
    insert_quarter_data,
)
from app.models import AnnualLimitsData, Service
from tests.app.db import create_service


class TestGetPreviousQuarter:
    @pytest.mark.parametrize(
        "date_to_check, expected",
        [
            (datetime(2021, 4, 1), ("Q4-2020", (datetime(2021, 1, 1, 0, 0), datetime(2021, 3, 31, 23, 59, 59)))),
            (datetime(2021, 6, 1), ("Q4-2020", (datetime(2021, 1, 1, 0, 0), datetime(2021, 3, 31, 23, 59, 59)))),
            (datetime(2021, 9, 1), ("Q1-2021", (datetime(2021, 4, 1, 0, 0), datetime(2021, 6, 30, 23, 59, 59)))),
            (datetime(2021, 12, 1), ("Q2-2021", (datetime(2021, 7, 1, 0, 0), datetime(2021, 9, 30, 23, 59, 59)))),
            (datetime(2022, 1, 1), ("Q3-2021", (datetime(2021, 10, 1, 0, 0), datetime(2021, 12, 31, 23, 59, 59)))),
            (datetime(2022, 3, 31), ("Q3-2021", (datetime(2021, 10, 1, 0, 0), datetime(2021, 12, 31, 23, 59, 59)))),
            (datetime(2023, 5, 5), ("Q4-2022", (datetime(2023, 1, 1, 0, 0), datetime(2023, 3, 31, 23, 59, 59)))),
        ],
    )
    def test_get_previous_quarter(self, date_to_check, expected):
        assert get_previous_quarter(date_to_check) == expected


class TestInsertQuarterData:
    def test_insert_quarter_data(self, notify_db_session):
        service_1 = create_service(service_name="service_1")
        service_2 = create_service(service_name="service_2")

        service_info = {x.id: (x.email_annual_limit, x.sms_annual_limit) for x in Service.query.all()}
        NotificationData = namedtuple("NotificationData", ["service_id", "notification_type", "notification_count"])

        data = [
            NotificationData(service_1.id, "sms", 4),
            NotificationData(service_2.id, "sms", 1100),
            NotificationData(service_1.id, "email", 2),
        ]
        insert_quarter_data(data, "Q1-2018", service_info)

        assert AnnualLimitsData.query.count() == 3

        # We want to check what happens when the same primary key but a new notification count is introduced

        assert AnnualLimitsData.query.filter_by(service_id=service_2.id).first().notification_count == 1100
        insert_quarter_data(
            [
                NotificationData(service_2.id, "sms", 500),
            ],
            "Q1-2018",
            service_info,
        )
        assert AnnualLimitsData.query.filter_by(service_id=service_2.id).first().notification_count == 500


class TestFetchCummulativeStats:
    def test_fetch_quarter_cummulative_stats(self, notify_db_session):
        service_1 = create_service(service_name="service_1")
        service_2 = create_service(service_name="service_2")

        service_info = {x.id: (x.email_annual_limit, x.sms_annual_limit) for x in Service.query.all()}
        NotificationData = namedtuple("NotificationData", ["service_id", "notification_type", "notification_count"])

        data = [
            NotificationData(service_1.id, "sms", 4),
            NotificationData(service_2.id, "sms", 1100),
            NotificationData(service_1.id, "email", 2),
        ]
        insert_quarter_data(data, "Q1-2018", service_info)

        data2 = [NotificationData(service_1.id, "sms", 5)]
        insert_quarter_data(data2, "Q2-2018", service_info)

        result = fetch_quarter_cummulative_stats(["Q1-2018", "Q2-2018"], [service_1.id, service_2.id])
        for service_id, counts in result:
            if service_id == service_1.id:
                assert counts == {"sms": 9, "email": 2}
            if service_id == service_2.id:
                assert counts == {"sms": 1100}
