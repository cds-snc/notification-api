from unittest.mock import call

import boto3
import pytest

from freezegun import freeze_time

from sqlalchemy.orm.exc import NoResultFound

from app.celery.letters_pdf_tasks import (
    collate_letter_pdfs_for_day,
    create_letters_pdf,
    group_letters,
    letter_in_created_state,
    process_virus_scan_error,
    process_virus_scan_failed,
    process_virus_scan_passed,
    replay_letters_in_error,
)

from app.models import (
    LETTER_TYPE,
    NOTIFICATION_CREATED,
    NOTIFICATION_SENDING,
)

from tests.conftest import set_config_values


def test_should_have_decorated_tasks_functions():
    assert create_letters_pdf.__wrapped__.__name__ == 'create_letters_pdf'
    assert collate_letter_pdfs_for_day.__wrapped__.__name__ == 'collate_letter_pdfs_for_day'
    assert process_virus_scan_passed.__wrapped__.__name__ == 'process_virus_scan_passed'
    assert process_virus_scan_failed.__wrapped__.__name__ == 'process_virus_scan_failed'
    assert process_virus_scan_error.__wrapped__.__name__ == 'process_virus_scan_error'


def test_create_letters_pdf_non_existent_notification(notify_api, mocker, fake_uuid):
    with pytest.raises(expected_exception=NoResultFound):
        create_letters_pdf(fake_uuid)


def test_collate_letter_pdfs_for_day(notify_api, mocker):
    mock_s3 = mocker.patch(
        'app.celery.tasks.s3.get_s3_bucket_objects',
        return_value=[{'Key': 'B.pDf', 'Size': 2}, {'Key': 'A.PDF', 'Size': 1}, {'Key': 'C.pdf', 'Size': 3}],
    )
    mock_group_letters = mocker.patch(
        'app.celery.letters_pdf_tasks.group_letters',
        return_value=[[{'Key': 'A.PDF', 'Size': 1}, {'Key': 'B.pDf', 'Size': 2}], [{'Key': 'C.pdf', 'Size': 3}]],
    )
    mock_celery = mocker.patch('app.celery.letters_pdf_tasks.notify_celery.send_task')

    collate_letter_pdfs_for_day('2017-01-02')

    mock_s3.assert_called_once_with('test-letters-pdf', subfolder='2017-01-02')
    mock_group_letters.assert_called_once_with(sorted(mock_s3.return_value, key=lambda x: x['Key']))
    assert mock_celery.call_args_list[0] == call(
        name='zip-and-send-letter-pdfs',
        kwargs={
            'filenames_to_zip': ['A.PDF', 'B.pDf'],
            'upload_filename': 'NOTIFY.2017-01-02.001.oqdjIM2-NAUU9Sm5Slmi.ZIP',
        },
        queue='process-ftp-tasks',
        compression='zlib',
    )
    assert mock_celery.call_args_list[1] == call(
        name='zip-and-send-letter-pdfs',
        kwargs={'filenames_to_zip': ['C.pdf'], 'upload_filename': 'NOTIFY.2017-01-02.002.tdr7hcdPieiqjkVoS4kU.ZIP'},
        queue='process-ftp-tasks',
        compression='zlib',
    )


@freeze_time('2018-09-12 17:50:00')
def test_collate_letter_pdfs_for_day_works_without_date_param(notify_api, mocker):
    mock_s3 = mocker.patch('app.celery.tasks.s3.get_s3_bucket_objects')
    collate_letter_pdfs_for_day()
    expected_date = '2018-09-12'
    mock_s3.assert_called_once_with('test-letters-pdf', subfolder=expected_date)


def test_group_letters_splits_on_file_size(notify_api, mocker):
    mocker.patch('app.celery.letters_pdf_tasks.letter_in_created_state', return_value=True)
    letters = [
        # ends under max but next one is too big
        {'Key': 'A.pdf', 'Size': 1},
        {'Key': 'B.pdf', 'Size': 2},
        # ends on exactly max
        {'Key': 'C.pdf', 'Size': 3},
        {'Key': 'D.pdf', 'Size': 1},
        {'Key': 'E.pdf', 'Size': 1},
        # exactly max goes in next file
        {'Key': 'F.pdf', 'Size': 5},
        # if it's bigger than the max, still gets included
        {'Key': 'G.pdf', 'Size': 6},
        # whatever's left goes in last list
        {'Key': 'H.pdf', 'Size': 1},
        {'Key': 'I.pdf', 'Size': 1},
    ]

    with set_config_values(notify_api, {'MAX_LETTER_PDF_ZIP_FILESIZE': 5}):
        x = group_letters(letters)

        assert next(x) == [{'Key': 'A.pdf', 'Size': 1}, {'Key': 'B.pdf', 'Size': 2}]
        assert next(x) == [{'Key': 'C.pdf', 'Size': 3}, {'Key': 'D.pdf', 'Size': 1}, {'Key': 'E.pdf', 'Size': 1}]
        assert next(x) == [{'Key': 'F.pdf', 'Size': 5}]
        assert next(x) == [{'Key': 'G.pdf', 'Size': 6}]
        assert next(x) == [{'Key': 'H.pdf', 'Size': 1}, {'Key': 'I.pdf', 'Size': 1}]
        # make sure iterator is exhausted
        assert next(x, None) is None


def test_group_letters_splits_on_file_count(notify_api, mocker):
    mocker.patch('app.celery.letters_pdf_tasks.letter_in_created_state', return_value=True)
    letters = [
        {'Key': 'A.pdf', 'Size': 1},
        {'Key': 'B.pdf', 'Size': 2},
        {'Key': 'C.pdf', 'Size': 3},
        {'Key': 'D.pdf', 'Size': 1},
        {'Key': 'E.pdf', 'Size': 1},
        {'Key': 'F.pdf', 'Size': 5},
        {'Key': 'G.pdf', 'Size': 6},
        {'Key': 'H.pdf', 'Size': 1},
        {'Key': 'I.pdf', 'Size': 1},
    ]

    with set_config_values(notify_api, {'MAX_LETTER_PDF_COUNT_PER_ZIP': 3}):
        x = group_letters(letters)

        assert next(x) == [{'Key': 'A.pdf', 'Size': 1}, {'Key': 'B.pdf', 'Size': 2}, {'Key': 'C.pdf', 'Size': 3}]
        assert next(x) == [{'Key': 'D.pdf', 'Size': 1}, {'Key': 'E.pdf', 'Size': 1}, {'Key': 'F.pdf', 'Size': 5}]
        assert next(x) == [{'Key': 'G.pdf', 'Size': 6}, {'Key': 'H.pdf', 'Size': 1}, {'Key': 'I.pdf', 'Size': 1}]
        # make sure iterator is exhausted
        assert next(x, None) is None


def test_group_letters_splits_on_file_size_and_file_count(notify_api, mocker):
    mocker.patch('app.celery.letters_pdf_tasks.letter_in_created_state', return_value=True)
    letters = [
        # ends under max file size but next file is too big
        {'Key': 'A.pdf', 'Size': 1},
        {'Key': 'B.pdf', 'Size': 2},
        # ends on exactly max number of files and file size
        {'Key': 'C.pdf', 'Size': 3},
        {'Key': 'D.pdf', 'Size': 1},
        {'Key': 'E.pdf', 'Size': 1},
        # exactly max file size goes in next file
        {'Key': 'F.pdf', 'Size': 5},
        # file size is within max but number of files reaches limit
        {'Key': 'G.pdf', 'Size': 1},
        {'Key': 'H.pdf', 'Size': 1},
        {'Key': 'I.pdf', 'Size': 1},
        # whatever's left goes in last list
        {'Key': 'J.pdf', 'Size': 1},
    ]

    with set_config_values(notify_api, {'MAX_LETTER_PDF_ZIP_FILESIZE': 5, 'MAX_LETTER_PDF_COUNT_PER_ZIP': 3}):
        x = group_letters(letters)

        assert next(x) == [{'Key': 'A.pdf', 'Size': 1}, {'Key': 'B.pdf', 'Size': 2}]
        assert next(x) == [{'Key': 'C.pdf', 'Size': 3}, {'Key': 'D.pdf', 'Size': 1}, {'Key': 'E.pdf', 'Size': 1}]
        assert next(x) == [{'Key': 'F.pdf', 'Size': 5}]
        assert next(x) == [{'Key': 'G.pdf', 'Size': 1}, {'Key': 'H.pdf', 'Size': 1}, {'Key': 'I.pdf', 'Size': 1}]
        assert next(x) == [{'Key': 'J.pdf', 'Size': 1}]
        # make sure iterator is exhausted
        assert next(x, None) is None


def test_group_letters_ignores_non_pdfs(notify_api, mocker):
    mocker.patch('app.celery.letters_pdf_tasks.letter_in_created_state', return_value=True)
    letters = [{'Key': 'A.zip'}]
    assert list(group_letters(letters)) == []


def test_group_letters_ignores_notifications_already_sent(notify_api, mocker):
    mock = mocker.patch('app.celery.letters_pdf_tasks.letter_in_created_state', return_value=False)
    letters = [{'Key': 'A.pdf'}]
    assert list(group_letters(letters)) == []
    mock.assert_called_once_with('A.pdf')


def test_group_letters_with_no_letters(notify_api, mocker):
    mocker.patch('app.celery.letters_pdf_tasks.letter_in_created_state', return_value=True)
    assert list(group_letters([])) == []


def test_letter_in_created_state(sample_template, sample_notification):
    template = sample_template(template_type=LETTER_TYPE)
    sample_notification(template=template, reference='ABCDEF1234567890', status=NOTIFICATION_CREATED)
    sample_notification.reference = 'ABCDEF1234567890'
    filename = '2018-01-13/NOTIFY.ABCDEF1234567890.D.2.C.C.20180113120000.PDF'
    assert letter_in_created_state(filename) is True


def test_letter_in_created_state_fails_if_notification_not_in_created(sample_template, sample_notification):
    template = sample_template(template_type=LETTER_TYPE)
    sample_notification(template=template, reference='ABCDEF1234567890', status=NOTIFICATION_SENDING)
    filename = '2018-01-13/NOTIFY.ABCDEF1234567890.D.2.C.C.20180113120000.PDF'
    assert letter_in_created_state(filename) is False


def test_letter_in_created_state_fails_if_notification_doesnt_exist(sample_template, sample_notification):
    template = sample_template(template_type=LETTER_TYPE)
    sample_notification(template=template, reference='QWERTY1234567890')
    filename = '2018-01-13/NOTIFY.ABCDEF1234567890.D.2.C.C.20180113120000.PDF'
    assert letter_in_created_state(filename) is False


def test_replay_letters_in_error_for_all_letters_in_error_bucket(notify_api, mocker):
    mockObject = boto3.resource('s3').Object('ERROR', 'ERROR/file_name')
    mocker.patch('app.celery.letters_pdf_tasks.get_file_names_from_error_bucket', return_value=[mockObject])
    mock_move = mocker.patch('app.celery.letters_pdf_tasks.move_error_pdf_to_scan_bucket')
    mock_celery = mocker.patch('app.celery.letters_pdf_tasks.notify_celery.send_task')
    replay_letters_in_error()
    mock_move.assert_called_once_with('file_name')
    mock_celery.assert_called_once_with(name='scan-file', kwargs={'filename': 'file_name'}, queue='antivirus-tasks')


def test_replay_letters_in_error_for_one_file(notify_api, mocker):
    mockObject = boto3.resource('s3').Object('ERROR', 'ERROR/file_name')
    mocker.patch('app.celery.letters_pdf_tasks.get_file_names_from_error_bucket', return_value=[mockObject])
    mock_move = mocker.patch('app.celery.letters_pdf_tasks.move_error_pdf_to_scan_bucket')
    mock_celery = mocker.patch('app.celery.letters_pdf_tasks.notify_celery.send_task')
    replay_letters_in_error('file_name')
    mock_move.assert_called_once_with('file_name')
    mock_celery.assert_called_once_with(name='scan-file', kwargs={'filename': 'file_name'}, queue='antivirus-tasks')
