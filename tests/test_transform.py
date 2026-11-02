from datetime import datetime

import pytest

from grader_etl.transform import (ValidationError, parse_passback_params,
                                  parse_record, transform)

PASSBACK = ("{'oauth_consumer_key': '', "
            "'lis_result_sourcedid': 'course-v1:org+course+2026:lms:abc', "
            "'lis_outcome_service_url': 'https://lms.example/grade_handler'}")


def make_record(**changes):
    record = {
        'lti_user_id': 'user-0001',
        'passback_params': PASSBACK,
        'is_correct': None,
        'attempt_type': 'run',
        'created_at': '2023-05-31 09:16:11.313646',
    }
    record.update(changes)
    return record


def test_valid_record():
    attempt = parse_record(make_record())
    assert attempt.user_id == 'user-0001'
    assert attempt.oauth_consumer_key is None            # пустой ключ -> NULL
    assert attempt.lis_result_sourcedid == 'course-v1:org+course+2026:lms:abc'
    assert attempt.lis_outcome_service_url == 'https://lms.example/grade_handler'
    assert attempt.is_correct is None
    assert attempt.attempt_type == 'run'
    assert attempt.created_at == datetime(2023, 5, 31, 9, 16, 11, 313646)


@pytest.mark.parametrize('raw, expected', [(1, True), (0, False), (None, None),
                                           (True, True), (False, False)])
def test_is_correct_normalized(raw, expected):
    record = make_record(attempt_type='submit', is_correct=raw)
    assert parse_record(record).is_correct is expected


def test_consumer_key_kept_and_extra_keys_ignored():
    passback = ("{'oauth_consumer_key': 'key1', 'lis_result_sourcedid': 's', "
                "'lis_outcome_service_url': 'u', 'unexpected': 123}")
    attempt = parse_record(make_record(passback_params=passback))
    assert attempt.oauth_consumer_key == 'key1'


def test_missing_consumer_key_is_allowed():
    passback = "{'lis_result_sourcedid': 's', 'lis_outcome_service_url': 'u'}"
    assert parse_record(make_record(passback_params=passback)).oauth_consumer_key is None


def test_missing_outcome_url_is_allowed():
    passback = "{'oauth_consumer_key': '', 'lis_result_sourcedid': 's'}"
    attempt = parse_record(make_record(passback_params=passback))
    assert attempt.lis_outcome_service_url is None
    assert attempt.lis_result_sourcedid == 's'


def test_json_passback_is_supported():
    params = parse_passback_params('{"a": "b"}')
    assert params == {'a': 'b'}


def test_created_without_microseconds():
    attempt = parse_record(make_record(created_at='2023-05-31 09:16:11'))
    assert attempt.created_at == datetime(2023, 5, 31, 9, 16, 11)


@pytest.mark.parametrize('changes', [
    {'passback_params': None},
    {'passback_params': ''},
    {'passback_params': "{'lis_result_sourcedid': 's'"},          # обрыв строки
    {'passback_params': "['not', 'a', 'dict']"},
    {'passback_params': "{'oauth_consumer_key': '', 'lis_outcome_service_url': 'u'}"},
    {'passback_params': "{'oauth_consumer_key': '', 'lis_result_sourcedid': 's', "
                        "'lis_outcome_service_url': 7}"},
    {'passback_params': "{'oauth_consumer_key': 5, 'lis_result_sourcedid': 's', "
                        "'lis_outcome_service_url': 'u'}"},
    {'passback_params': "{'lis_result_sourcedid': '', 'lis_outcome_service_url': 'u'}"},
    {'attempt_type': 'other'},
    {'attempt_type': None},
    {'is_correct': 2},
    {'is_correct': 'yes'},
    {'created_at': 'вчера'},
    {'created_at': None},
    {'created_at': 12345},
    {'lti_user_id': ''},
    {'lti_user_id': None},
    {'lti_user_id': 42},
])
def test_invalid_records_are_rejected(changes):
    with pytest.raises(ValidationError):
        parse_record(make_record(**changes))


@pytest.mark.parametrize('record', [None, 'text', 5, ['x']])
def test_non_dict_record_is_rejected(record):
    with pytest.raises(ValidationError):
        parse_record(record)


def test_transform_counts_and_logs_skipped(caplog):
    records = [make_record(), make_record(attempt_type='bad'), make_record(is_correct=1,
               attempt_type='submit'), None]
    with caplog.at_level('WARNING'):
        attempts, skipped = transform(records)
    assert len(attempts) == 2
    assert skipped == 2
    assert 'Запись #1 пропущена' in caplog.text
    assert 'Запись #3 пропущена' in caplog.text


# --- правки по ревью 31.10.2026: связка attempt_type и is_correct, время со смещением

@pytest.mark.parametrize('is_correct', [True, False, 1, 0])
def test_run_with_is_correct_is_rejected(is_correct):
    with pytest.raises(ValidationError, match="'run'"):
        parse_record(make_record(attempt_type='run', is_correct=is_correct))


def test_run_with_null_is_correct_is_valid():
    assert parse_record(make_record(attempt_type='run', is_correct=None)).is_correct is None


def test_submit_may_have_null_is_correct():
    assert parse_record(make_record(attempt_type='submit', is_correct=None)).is_correct is None


def test_transform_skips_run_with_is_correct_and_keeps_others():
    records = [make_record(attempt_type='run', is_correct=None),
               make_record(attempt_type='run', is_correct=True),
               make_record(attempt_type='submit', is_correct=False)]
    attempts, skipped = transform(records)
    assert len(attempts) == 2 and skipped == 1


@pytest.mark.parametrize('raw, expected', [
    ('2026-05-31 12:00:00+03:00', datetime(2026, 5, 31, 9, 0, 0)),
    ('2026-05-31T12:00:00Z', datetime(2026, 5, 31, 12, 0, 0)),
    ('2026-05-31 23:30:00-05:00', datetime(2026, 6, 1, 4, 30, 0)),   # сутки сменились
    ('2026-05-31 12:00:00', datetime(2026, 5, 31, 12, 0, 0)),        # без смещения: уже UTC
])
def test_created_at_is_converted_to_naive_utc(raw, expected):
    attempt = parse_record(make_record(created_at=raw))
    assert attempt.created_at == expected
    assert attempt.created_at.tzinfo is None
