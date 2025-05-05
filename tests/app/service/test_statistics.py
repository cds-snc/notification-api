import collections

from freezegun import freeze_time
import pytest

from app.constants import (
    EMAIL_TYPE,
    LETTER_TYPE,
    NOTIFICATION_CANCELLED,
    NOTIFICATION_CREATED,
    NOTIFICATION_DELIVERED,
    NOTIFICATION_FAILED,
    NOTIFICATION_PENDING_VIRUS_CHECK,
    NOTIFICATION_PERMANENT_FAILURE,
    NOTIFICATION_SENDING,
    NOTIFICATION_SENT,
    NOTIFICATION_TEMPORARY_FAILURE,
    NOTIFICATION_VALIDATION_FAILED,
    NOTIFICATION_VIRUS_SCAN_FAILED,
    SMS_TYPE,
)
from app.service.statistics import (
    format_admin_stats,
    format_statistics,
    create_stats_dict,
    create_zeroed_stats_dicts,
    create_empty_monthly_notification_status_stats_dict,
)

StatsRow = collections.namedtuple('row', ('notification_type', 'status', 'count'))
NewStatsRow = collections.namedtuple('row', ('notification_type', 'status', 'key_type', 'count'))


# email_counts and sms_counts are 3-tuple of requested, delivered, failed
@pytest.mark.idparametrize(
    'stats, email_counts, sms_counts, letter_counts',
    {
        'empty': ([], [0, 0, 0], [0, 0, 0], [0, 0, 0]),
        'always_increment_requested': (
            [StatsRow(EMAIL_TYPE, NOTIFICATION_DELIVERED, 1), StatsRow(EMAIL_TYPE, NOTIFICATION_FAILED, 1)],
            [2, 1, 1],
            [0, 0, 0],
            [0, 0, 0],
        ),
        'dont_mix_template_types': (
            [
                StatsRow(EMAIL_TYPE, NOTIFICATION_DELIVERED, 1),
                StatsRow(SMS_TYPE, NOTIFICATION_DELIVERED, 1),
                StatsRow(LETTER_TYPE, NOTIFICATION_DELIVERED, 1),
            ],
            [1, 1, 0],
            [1, 1, 0],
            [1, 1, 0],
        ),
        'convert_fail_statuses_to_failed': (
            [
                StatsRow(EMAIL_TYPE, NOTIFICATION_FAILED, 1),
                StatsRow(EMAIL_TYPE, NOTIFICATION_TEMPORARY_FAILURE, 1),
                StatsRow(EMAIL_TYPE, NOTIFICATION_PERMANENT_FAILURE, 2),
                StatsRow(LETTER_TYPE, NOTIFICATION_VALIDATION_FAILED, 1),
                StatsRow(LETTER_TYPE, NOTIFICATION_VIRUS_SCAN_FAILED, 1),
                StatsRow(LETTER_TYPE, NOTIFICATION_PERMANENT_FAILURE, 1),
                StatsRow(LETTER_TYPE, NOTIFICATION_CANCELLED, 1),
            ],
            [4, 0, 4],
            [0, 0, 0],
            [3, 0, 3],
        ),
        'convert_sent_to_delivered': (
            [
                StatsRow(SMS_TYPE, NOTIFICATION_SENDING, 1),
                StatsRow(SMS_TYPE, NOTIFICATION_DELIVERED, 1),
                StatsRow(SMS_TYPE, NOTIFICATION_SENT, 1),
            ],
            [0, 0, 0],
            [3, 2, 0],
            [0, 0, 0],
        ),
        'handles_none_rows': (
            [StatsRow(SMS_TYPE, NOTIFICATION_SENDING, 1), StatsRow(None, None, None)],
            [0, 0, 0],
            [1, 0, 0],
            [0, 0, 0],
        ),
    },
)
def test_format_statistics(stats, email_counts, sms_counts, letter_counts):
    ret = format_statistics(stats)

    assert ret[EMAIL_TYPE] == {
        status: count for status, count in zip(['requested', NOTIFICATION_DELIVERED, NOTIFICATION_FAILED], email_counts)
    }

    assert ret[SMS_TYPE] == {
        status: count for status, count in zip(['requested', NOTIFICATION_DELIVERED, NOTIFICATION_FAILED], sms_counts)
    }

    assert ret[LETTER_TYPE] == {
        status: count
        for status, count in zip(['requested', NOTIFICATION_DELIVERED, NOTIFICATION_FAILED], letter_counts)
    }


def test_create_zeroed_stats_dicts():
    assert create_zeroed_stats_dicts() == {
        SMS_TYPE: {'requested': 0, NOTIFICATION_DELIVERED: 0, NOTIFICATION_FAILED: 0},
        EMAIL_TYPE: {'requested': 0, NOTIFICATION_DELIVERED: 0, NOTIFICATION_FAILED: 0},
        LETTER_TYPE: {'requested': 0, NOTIFICATION_DELIVERED: 0, NOTIFICATION_FAILED: 0},
    }


def test_create_stats_dict():
    assert create_stats_dict() == {
        SMS_TYPE: {
            'total': 0,
            'test-key': 0,
            'failures': {
                NOTIFICATION_PERMANENT_FAILURE: 0,
                NOTIFICATION_TEMPORARY_FAILURE: 0,
                NOTIFICATION_VIRUS_SCAN_FAILED: 0,
            },
        },
        EMAIL_TYPE: {
            'total': 0,
            'test-key': 0,
            'failures': {
                NOTIFICATION_PERMANENT_FAILURE: 0,
                NOTIFICATION_TEMPORARY_FAILURE: 0,
                NOTIFICATION_VIRUS_SCAN_FAILED: 0,
            },
        },
        LETTER_TYPE: {
            'total': 0,
            'test-key': 0,
            'failures': {
                NOTIFICATION_PERMANENT_FAILURE: 0,
                NOTIFICATION_TEMPORARY_FAILURE: 0,
                NOTIFICATION_VIRUS_SCAN_FAILED: 0,
            },
        },
    }


def test_format_admin_stats_only_includes_test_key_notifications_in_test_key_section():
    rows = [
        NewStatsRow(EMAIL_TYPE, NOTIFICATION_PERMANENT_FAILURE, 'test', 3),
        NewStatsRow(SMS_TYPE, NOTIFICATION_PERMANENT_FAILURE, 'test', 4),
        NewStatsRow(LETTER_TYPE, NOTIFICATION_VIRUS_SCAN_FAILED, 'test', 5),
    ]
    stats_dict = format_admin_stats(rows)

    assert stats_dict[EMAIL_TYPE]['total'] == 0
    assert stats_dict[EMAIL_TYPE]['failures'][NOTIFICATION_PERMANENT_FAILURE] == 0
    assert stats_dict[EMAIL_TYPE]['test-key'] == 3

    assert stats_dict[SMS_TYPE]['total'] == 0
    assert stats_dict[SMS_TYPE]['failures'][NOTIFICATION_PERMANENT_FAILURE] == 0
    assert stats_dict[SMS_TYPE]['test-key'] == 4

    assert stats_dict[LETTER_TYPE]['total'] == 0
    assert stats_dict[LETTER_TYPE]['failures'][NOTIFICATION_VIRUS_SCAN_FAILED] == 0
    assert stats_dict[LETTER_TYPE]['test-key'] == 5


def test_format_admin_stats_counts_non_test_key_notifications_correctly():
    rows = [
        NewStatsRow(EMAIL_TYPE, NOTIFICATION_PERMANENT_FAILURE, 'normal', 1),
        NewStatsRow(EMAIL_TYPE, NOTIFICATION_CREATED, 'team', 3),
        NewStatsRow(SMS_TYPE, NOTIFICATION_TEMPORARY_FAILURE, 'normal', 6),
        NewStatsRow(SMS_TYPE, NOTIFICATION_SENT, 'normal', 2),
        NewStatsRow(LETTER_TYPE, NOTIFICATION_PENDING_VIRUS_CHECK, 'normal', 1),
    ]
    stats_dict = format_admin_stats(rows)

    assert stats_dict[EMAIL_TYPE]['total'] == 4
    assert stats_dict[EMAIL_TYPE]['failures'][NOTIFICATION_PERMANENT_FAILURE] == 1

    assert stats_dict[SMS_TYPE]['total'] == 8
    assert stats_dict[SMS_TYPE]['failures'][NOTIFICATION_PERMANENT_FAILURE] == 0

    assert stats_dict[LETTER_TYPE]['total'] == 1


def _stats(requested, delivered, failed):
    return {'requested': requested, NOTIFICATION_DELIVERED: delivered, NOTIFICATION_FAILED: failed}


@pytest.mark.parametrize(
    'year, expected_years',
    [
        (2018, ['2018-04', '2018-05', '2018-06']),
        (
            2017,
            [
                '2017-04',
                '2017-05',
                '2017-06',
                '2017-07',
                '2017-08',
                '2017-09',
                '2017-10',
                '2017-11',
                '2017-12',
                '2018-01',
                '2018-02',
                '2018-03',
            ],
        ),
    ],
)
@freeze_time('2018-06-01 04:59:59')
# This test assumes the local timezone is EST
def test_create_empty_monthly_notification_status_stats_dict(year, expected_years):
    output = create_empty_monthly_notification_status_stats_dict(year)
    assert sorted(output.keys()) == expected_years
    for v in output.values():
        assert v == {SMS_TYPE: {}, EMAIL_TYPE: {}, LETTER_TYPE: {}}
