import smtplib
from datetime import date, datetime
from unittest import mock

import pytest

import main
from grader_etl import notify, sheets

STATS = {'date': '2026-05-31', 'total_attempts': 10, 'run_attempts': 4,
         'submit_attempts': 6, 'correct_submits': 3, 'success_rate': 50.0,
         'unique_users': 5, 'unique_tasks': 3}


# --- почта ---------------------------------------------------------------
def test_email_is_sent_over_ssl(settings):
    with mock.patch.object(notify.smtplib, 'SMTP_SSL') as smtp:
        assert notify.send_email(settings, 'Тема', 'Текст') is True
    server = smtp.return_value.__enter__.return_value
    server.login.assert_called_once_with('me@example.test', 'app-password')
    message = server.send_message.call_args.args[0]
    assert message['Subject'] == 'Тема'
    assert message['To'] == 'me@example.test'


def test_email_failure_does_not_raise(settings, caplog):
    with mock.patch.object(notify.smtplib, 'SMTP_SSL',
                           side_effect=smtplib.SMTPAuthenticationError(535, b'bad')):
        with caplog.at_level('ERROR'):
            assert notify.send_email(settings, 'Тема', 'Текст') is False
    assert 'Не удалось отправить письмо' in caplog.text


def test_email_skipped_when_not_configured(settings):
    from dataclasses import replace
    no_mail = replace(settings, smtp_password='')
    with mock.patch.object(notify.smtplib, 'SMTP_SSL') as smtp:
        assert notify.send_email(no_mail, 'Тема', 'Текст') is False
    smtp.assert_not_called()


# --- Google Sheets ---------------------------------------------------------
def make_sheet(existing_dates, header=None):
    worksheet = mock.Mock()
    worksheet.row_values.return_value = header if header is not None else sheets.HEADER
    worksheet.col_values.return_value = ['date'] + existing_dates
    spreadsheet = mock.Mock()
    spreadsheet.worksheet.return_value = worksheet
    client = mock.Mock()
    client.open_by_key.return_value = spreadsheet
    return client, worksheet


def test_sheets_appends_new_day(tmp_path):
    client, worksheet = make_sheet(['2026-05-30'])
    with mock.patch.object(sheets.gspread, 'service_account', return_value=client):
        sheets.upload_daily_stats([STATS], tmp_path / 'k.json', 'id')
    worksheet.append_row.assert_called_once()
    assert worksheet.append_row.call_args.args[0][:3] == ['2026-05-31', 10, 4]
    worksheet.update.assert_not_called()


def test_sheets_updates_existing_day(tmp_path):
    client, worksheet = make_sheet(['2026-05-30', '2026-05-31'])
    with mock.patch.object(sheets.gspread, 'service_account', return_value=client):
        sheets.upload_daily_stats([STATS], tmp_path / 'k.json', 'id')
    worksheet.update.assert_called_once()
    assert worksheet.update.call_args.kwargs['range_name'] == 'A3'
    worksheet.append_row.assert_not_called()


def test_sheets_writes_header_when_missing(tmp_path):
    client, worksheet = make_sheet([], header=[])
    with mock.patch.object(sheets.gspread, 'service_account', return_value=client):
        sheets.upload_daily_stats([STATS], tmp_path / 'k.json', 'id')
    assert worksheet.update.call_args_list[0].kwargs['values'] == [sheets.HEADER]


# --- main --------------------------------------------------------------------
def test_default_range_is_yesterday():
    args = main.parse_args([])
    start, end = main.resolve_range(args, today=date(2026, 6, 1))
    assert start == datetime(2026, 5, 31, 0, 0)
    assert end == datetime(2026, 5, 31, 23, 59, 59, 999999)


def test_explicit_date_and_interval():
    start, end = main.resolve_range(main.parse_args(['--date', '2026-05-30']))
    assert start.date() == end.date() == date(2026, 5, 30)
    start, end = main.resolve_range(main.parse_args(
        ['--start', '2026-05-30 10:00:00', '--end', '2026-05-31 11:00:00']))
    assert (start, end) == (datetime(2026, 5, 30, 10), datetime(2026, 5, 31, 11))


@pytest.mark.parametrize('argv', [['--start', '2026-05-30 10:00:00'],
                                  ['--start', '2026-05-31', '--end', '2026-05-30']])
def test_invalid_range_is_rejected(argv):
    with pytest.raises(ValueError):
        main.resolve_range(main.parse_args(argv))


def test_email_body_contains_key_numbers():
    totals = {'downloaded': 12, 'valid': 10, 'skipped': 2, 'inserted': 9}
    body = main.build_email_body(datetime(2026, 5, 31), datetime(2026, 5, 31, 23, 59),
                                 totals, [STATS], 12.3, ['Google Sheets: ошибка'])
    for text in ('Скачано записей: 12', 'пропущено: 2', 'Добавлено в базу: 9',
                 '2026-05-31', '3 из 6', 'Google Sheets: ошибка'):
        assert text in body
