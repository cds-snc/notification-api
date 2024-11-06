from datetime import datetime

from sqlalchemy.dialects.postgresql import insert

from app import db
from app.models import AnnualLimitsData


def get_previous_quarter(date_to_check):
    year = date_to_check.year
    month = date_to_check.month

    if month in [1, 2, 3]:
        quarter = "Q3"
        year -= 1
        start_date = datetime(year, 10, 1)
        end_date = datetime(year, 12, 31, 23, 59, 59)
    elif month in [4, 5, 6]:
        quarter = "Q4"
        start_date = datetime(year, 1, 1)
        end_date = datetime(year, 3, 31, 23, 59, 59)
        year -= 1  # Cause we want to store it as Q4 of the previous year
    elif month in [7, 8, 9]:
        quarter = "Q1"
        start_date = datetime(year, 4, 1)
        end_date = datetime(year, 6, 30, 23, 59, 59)
    elif month in [10, 11, 12]:
        quarter = "Q2"
        start_date = datetime(year, 7, 1)
        end_date = datetime(year, 9, 30, 23, 59, 59)

    quarter_name = f"{quarter}-{year}"
    return quarter_name, (start_date, end_date)


def insert_quarter_data(data, quarter, service_info):
    """
    Insert data for each quarter into the database.

    Each row in transit_data is a namedtuple with the following fields:
    - service_id,
    - notification_type,
    - notification_count
    """

    table = AnnualLimitsData.__table__

    for row in data:
        stmt = (
            insert(table)
            .values(
                service_id=row.service_id,
                time_period=quarter,
                annual_email_limit=service_info[row.service_id][0],
                annual_sms_limit=service_info[row.service_id][1],
                notification_type=row.notification_type,
                notification_count=row.notification_count,
            )
            .on_conflict_do_update(
                index_elements=["service_id", "time_period", "notification_type"],
                set_={
                    "annual_email_limit": insert(table).excluded.annual_email_limit,
                    "annual_sms_limit": insert(table).excluded.annual_sms_limit,
                    "notification_count": insert(table).excluded.notification_count,
                },
            )
        )
        db.session.connection().execute(stmt)
        db.session.commit()


def fetch_quarter_data(service_ids):
    """
    Fetch notification_count for the given quarter for the service_ids.

    Args:
        service_ids: list of service_ids
    Returns:
        list of namedtuples with the following fields:
        - service_id,
        - notification_type,
        - notification_count
    """
    db.query(AnnualLimitsData).filter(AnnualLimitsData.service_id.in_(service_ids)).all()