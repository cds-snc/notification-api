from sqlalchemy import text
from datetime import datetime, timedelta
from lambda_functions.va_profile_remove_old_opt_outs.va_profile_remove_old_opt_outs import va_profile_remove_old_opt_outs_handler

INSERT_OPT_IN_OUT_RECORD = text(
    """INSERT INTO va_profile_local_cache(va_profile_id, communication_item_id,
    communication_channel_id, source_datetime, allowed)
    VALUES(:va_profile_id, :communication_item_id, :communication_channel_id,
    :source_datetime, :allowed)"""
)

REMOVE_OPTED_OUT_RECORDS_QUERY = text("""SELECT va_profile_remove_old_opt_outs();""")

COUNT = r"""SELECT COUNT(*) FROM va_profile_local_cache;"""

SELECT_COUNT_OF_SINGLE_OPTED_OUT_RECORD = text("""SELECT COUNT(*)
FROM va_profile_local_cache
WHERE va_profile_id=0
AND communication_item_id=5
AND communication_channel_id=0
AND allowed=False;""")


def setup_db(connection):
    """
    Using the given connection, truncate the VA Profile local cache, and call
    the stored procedure to add a specific row. This establishes a known state
    for testing. Truncating is necessary because the database side effects of
    executing the VA Profile lambda function are not rolled back at the
    conclusion of a test.
    """

    connection.execute("truncate va_profile_local_cache;")

    # Sanity check
    count_queryset = connection.execute(COUNT)
    assert count_queryset.fetchone()[0] == 0, "The cache should be empty at the start."

    expired_datetime = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%dT%H:%M:%S%z')

    insert_expired_record_opt_out = INSERT_OPT_IN_OUT_RECORD.bindparams(
        va_profile_id=0,
        communication_item_id=5,
        communication_channel_id=0,
        allowed=False,
        source_datetime=expired_datetime
    )

    connection.execute(insert_expired_record_opt_out)

    insert_expired_record_opt_in = INSERT_OPT_IN_OUT_RECORD.bindparams(
        va_profile_id=2,
        communication_item_id=5,
        communication_channel_id=4,
        allowed=True,
        source_datetime=expired_datetime
    )

    connection.execute(insert_expired_record_opt_in)

    insert_active_record_opt_out = INSERT_OPT_IN_OUT_RECORD.bindparams(
        va_profile_id=1,
        communication_item_id=5,
        communication_channel_id=3,
        allowed=False,
        source_datetime=datetime.now().strftime('%Y-%m-%dT%H:%M:%S%z')
    )

    connection.execute(insert_active_record_opt_out)

    count_records_currently_in_database = connection.execute(COUNT)
    assert count_records_currently_in_database.fetchone()[0] == 3, \
        "There should only be three records in the database."


def test_remove_opted_out_records_query(notify_db_session):
    """
    If the difference between the current time and source_datetime
    is greater than 24 hours, the stored function should delete the records.
    """

    with notify_db_session.engine.begin() as connection:
        setup_db(connection)

        select_count_of_opted_out_record = connection.execute(SELECT_COUNT_OF_SINGLE_OPTED_OUT_RECORD)
        assert select_count_of_opted_out_record.fetchone()[0] == 1, \
            "There should be one expired opt out to delete."
     
        connection.execute(REMOVE_OPTED_OUT_RECORDS_QUERY)

        count_queryset = connection.execute(COUNT)
        assert count_queryset.fetchone()[0] == 2, \
            "The stored function should have two records remaining."

        select_count_of_opted_out_record = connection.execute(SELECT_COUNT_OF_SINGLE_OPTED_OUT_RECORD)
        assert select_count_of_opted_out_record.fetchone()[0] == 0, \
            "The expired opt out should have been deleted."


def test_va_profile_remove_old_opt_outs_handler(notify_db, worker_id):
    """
    Test the VA profile remove old opt outs lambda function to remove records 
    that are opted out and greater than 24 hours old.
    """

    with notify_db.engine.begin() as connection:
        setup_db(connection)

        select_count_of_opted_out_record = connection.execute(SELECT_COUNT_OF_SINGLE_OPTED_OUT_RECORD)
        assert select_count_of_opted_out_record.fetchone()[0] == 1, \
            "There should be one expired opted out record."

    va_profile_remove_old_opt_outs_handler(worker_id=worker_id)

    with notify_db.engine.begin() as connection:
        count_queryset = connection.execute(COUNT)
        assert count_queryset.fetchone()[0] == 2, \
            "The lambda function should have two records remaining that are opted in."

        select_count_of_opted_out_record = connection.execute(SELECT_COUNT_OF_SINGLE_OPTED_OUT_RECORD)
        assert select_count_of_opted_out_record.fetchone()[0] == 0, \
            "The expired opt out should have been deleted."