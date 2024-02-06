import pytest
from app.models import VAProfileLocalCache
from datetime import datetime, timedelta
from lambda_functions.va_profile_remove_old_opt_outs.va_profile_remove_old_opt_outs_lambda import (
    REMOVE_OPTED_OUT_RECORDS_QUERY,
    va_profile_remove_old_opt_outs_handler,
)


@pytest.mark.serial
@pytest.mark.parametrize(
    'method', ['stored_procedure', 'lambda_handler']
)
def test_remove_opted_out_records_query(notify_db_session, sample_va_profile_local_cache, method):
    """
    If the difference between the current time and source_datetime is greater than 24 hours,
    the stored function should delete opt-out records.
    """

    source_datetime = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%dT%H:%M:%S%z')

    # This should be deleted.
    opt_out = sample_va_profile_local_cache(source_datetime, False)
    opt_out_id = opt_out.id

    # This should not be deleted.
    opt_out_newer = sample_va_profile_local_cache(datetime.now(), False)

    # This should not be deleted.
    opt_in = sample_va_profile_local_cache(source_datetime, True)

    assert notify_db_session.session.get(VAProfileLocalCache, opt_out_id) is not None
    assert notify_db_session.session.get(VAProfileLocalCache, opt_out_newer.id) is not None
    assert notify_db_session.session.get(VAProfileLocalCache, opt_in.id) is not None

    if method == 'stored_procedure':
        # This tests the stored procedure directly.
        notify_db_session.session.execute(REMOVE_OPTED_OUT_RECORDS_QUERY)
        notify_db_session.session.commit()
    else:
        # This tests the lambda handler, which calls the stored procedure.
        va_profile_remove_old_opt_outs_handler()

    # TODO 1636 - This should not be commented out.
    # assert notify_db_session.session.get(VAProfileLocalCache, opt_out_id) is None
    assert notify_db_session.session.get(VAProfileLocalCache, opt_out_newer.id) is not None
    assert notify_db_session.session.get(VAProfileLocalCache, opt_in.id) is not None

