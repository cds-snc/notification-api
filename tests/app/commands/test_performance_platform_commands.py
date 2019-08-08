from datetime import datetime

from app.commands import backfill_performance_platform_totals, backfill_processing_time


# This test assumes the local timezone is EST
def test_backfill_processing_time_works_for_correct_dates(mocker, notify_api):
    send_mock = mocker.patch('app.commands.send_processing_time_for_start_and_end')

    # backfill_processing_time is a click.Command object - if you try invoking the callback on its own, it
    # throws a `RuntimeError: There is no active click context.` - so get at the original function using __wrapped__
    backfill_processing_time.callback.__wrapped__(datetime(2017, 8, 1), datetime(2017, 8, 3))

    assert send_mock.call_count == 3
    send_mock.assert_any_call(datetime(2017, 8, 3, 4, 0), datetime(2017, 8, 4, 4, 0))
    send_mock.assert_any_call(datetime(2017, 8, 3, 4, 0), datetime(2017, 8, 4, 4, 0))
    send_mock.assert_any_call(datetime(2017, 8, 3, 4, 0), datetime(2017, 8, 4, 4, 0))


def test_backfill_totals_works_for_correct_dates(mocker, notify_api):
    send_mock = mocker.patch('app.commands.send_total_sent_notifications_to_performance_platform')

    # backfill_processing_time is a click.Command object - if you try invoking the callback on its own, it
    # throws a `RuntimeError: There is no active click context.` - so get at the original function using __wrapped__
    backfill_performance_platform_totals.callback.__wrapped__(datetime(2017, 8, 1), datetime(2017, 8, 3))

    assert send_mock.call_count == 3
    send_mock.assert_any_call(datetime(2017, 8, 1))
    send_mock.assert_any_call(datetime(2017, 8, 2))
    send_mock.assert_any_call(datetime(2017, 8, 3))
