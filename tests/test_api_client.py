from datetime import datetime
from unittest import mock

import pytest
import requests

from grader_etl import api_client
from grader_etl.api_client import ApiError, fetch_statistics, split_into_days

START = datetime(2026, 5, 31, 0, 0, 0)
END = datetime(2026, 5, 31, 23, 59, 59, 999999)


def response(status=200, payload=None, text=''):
    resp = mock.Mock()
    resp.status_code = status
    resp.text = text
    if isinstance(payload, Exception):
        resp.json.side_effect = payload
    else:
        resp.json.return_value = payload
    return resp


def fetch(settings, **kwargs):
    kwargs.setdefault('sleep', lambda seconds: None)
    return fetch_statistics(settings, START, END, **kwargs)


def test_success_sends_expected_params(settings, caplog):
    with mock.patch.object(api_client.requests, 'get',
                           return_value=response(payload=[{'a': 1}])) as get:
        with caplog.at_level('INFO'):
            data = fetch(settings)
    assert data == [{'a': 1}]
    params = get.call_args.kwargs['params']
    assert params == {'client': 'Client', 'client_key': 'SECRETKEY',
                      'start': '2026-05-31 00:00:00.000000',
                      'end': '2026-05-31 23:59:59.999999'}
    assert 'Скачивание началось' in caplog.text
    assert 'Скачивание завершено: 1 записей' in caplog.text


def test_client_error_is_logged_with_status_and_not_retried(settings, caplog):
    with mock.patch.object(api_client.requests, 'get',
                           return_value=response(403, text='forbidden')) as get:
        with caplog.at_level('ERROR'), pytest.raises(ApiError):
            fetch(settings)
    assert get.call_count == 1
    assert 'status_code=403' in caplog.text


def test_server_error_is_retried_then_fails(settings, caplog):
    sleeps = []
    with mock.patch.object(api_client.requests, 'get',
                           return_value=response(500, text='oops')) as get:
        with caplog.at_level('ERROR'), pytest.raises(ApiError):
            fetch(settings, retries=3, sleep=sleeps.append)
    assert get.call_count == 3
    assert sleeps == [2, 4]
    assert caplog.text.count('status_code=500') == 3


def test_recovers_after_server_error(settings):
    replies = [response(502), response(payload=[1, 2])]
    with mock.patch.object(api_client.requests, 'get', side_effect=replies):
        assert fetch(settings) == [1, 2]


def test_network_error_is_retried_and_key_is_redacted(settings, caplog):
    error = requests.ConnectionError('failed for url ...client_key=SECRETKEY')
    with mock.patch.object(api_client.requests, 'get', side_effect=error) as get:
        with caplog.at_level('ERROR'), pytest.raises(ApiError):
            fetch(settings, retries=2)
    assert get.call_count == 2
    assert 'SECRETKEY' not in caplog.text
    assert '***' in caplog.text


def test_non_json_answer_is_an_error(settings):
    with mock.patch.object(api_client.requests, 'get',
                           return_value=response(payload=ValueError('bad'))):
        with pytest.raises(ApiError):
            fetch(settings, retries=2)


def test_unexpected_json_shape_is_an_error(settings):
    with mock.patch.object(api_client.requests, 'get',
                           return_value=response(payload={'detail': 'x'})):
        with pytest.raises(ApiError):
            fetch(settings)


def test_split_into_days():
    chunks = split_into_days(datetime(2026, 5, 30, 12, 0), datetime(2026, 6, 1, 6, 0))
    assert chunks == [
        (datetime(2026, 5, 30, 12, 0), datetime(2026, 5, 30, 23, 59, 59, 999999)),
        (datetime(2026, 5, 31, 0, 0), datetime(2026, 5, 31, 23, 59, 59, 999999)),
        (datetime(2026, 6, 1, 0, 0), datetime(2026, 6, 1, 6, 0)),
    ]


# --- правки по ревью 31.10.2026: время со смещением

def test_parse_dt_converts_offset_to_naive_utc():
    from grader_etl.api_client import parse_dt
    assert parse_dt('2026-05-31 12:00:00+03:00') == datetime(2026, 5, 31, 9, 0, 0)
    assert parse_dt('2026-05-31 12:00:00').tzinfo is None


def test_split_into_days_accepts_interval_given_with_offset():
    from datetime import date
    from grader_etl.api_client import parse_dt
    start = parse_dt('2026-05-31 01:00:00+03:00')   # 30.05 22:00 UTC
    end = parse_dt('2026-05-31 12:00:00+03:00')     # 31.05 09:00 UTC
    chunks = split_into_days(start, end)
    assert [chunk[0].date() for chunk in chunks] == [date(2026, 5, 30), date(2026, 5, 31)]
    assert all(c[0].tzinfo is None and c[1].tzinfo is None for c in chunks)
