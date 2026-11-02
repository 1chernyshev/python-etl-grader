"""Обработка ответа API: разбор passback_params и валидация записей."""
import ast
import json
import logging
from dataclasses import dataclass
from datetime import datetime

from .timeutil import to_utc_naive

log = logging.getLogger(__name__)

ATTEMPT_TYPES = ('run', 'submit')


class ValidationError(ValueError):
    """Запись не прошла проверку; текст - причина для лога."""


@dataclass(frozen=True)
class Attempt:
    """Одна попытка студента в том виде, в котором она попадает в базу."""
    user_id: str
    oauth_consumer_key: str | None
    lis_result_sourcedid: str
    lis_outcome_service_url: str | None
    is_correct: bool | None
    attempt_type: str
    created_at: datetime


def parse_passback_params(raw):
    """passback_params приходит строкой вида "{'key': 'value', ...}".

    Это repr словаря Python, а не JSON, поэтому разбираем ast.literal_eval
    (он безопасен, в отличие от eval), а JSON оставляем запасным вариантом.
    """
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        raise ValidationError('passback_params пустой или не строка')
    try:
        params = ast.literal_eval(raw)
    except (ValueError, SyntaxError, MemoryError, RecursionError):
        try:
            params = json.loads(raw)
        except ValueError:
            raise ValidationError('passback_params не удалось разобрать') from None
    if not isinstance(params, dict):
        raise ValidationError('passback_params не является словарем')
    return params


def _required_text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f'{name} отсутствует или не строка')
    return value.strip()


def _parse_is_correct(value):
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    raise ValidationError(f'is_correct имеет недопустимое значение {value!r}')


def _parse_created_at(value):
    if not isinstance(value, str):
        raise ValidationError('created_at отсутствует или не строка')
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        raise ValidationError(f'created_at в неверном формате: {value!r}') from None
    return to_utc_naive(parsed)


def parse_record(record):
    """Превращает запись API в Attempt или бросает ValidationError.

    Необязательны oauth_consumer_key (в данных бывает пустым) и
    lis_outcome_service_url (у части записей, в основном у run, его нет):
    в этих случаях в базу пишем NULL, а сама попытка остается в статистике.
    Остальные поля обязательны. Для run результат проверки is_correct должен
    быть NULL, для submit может быть true, false или NULL.
    Время со смещением часового пояса переводится в UTC.
    """
    if not isinstance(record, dict):
        raise ValidationError('запись не является словарем')
    params = parse_passback_params(record.get('passback_params'))

    attempt_type = record.get('attempt_type')
    if attempt_type not in ATTEMPT_TYPES:
        raise ValidationError(f'attempt_type имеет недопустимое значение {attempt_type!r}')

    consumer_key = params.get('oauth_consumer_key')
    if consumer_key is not None and not isinstance(consumer_key, str):
        raise ValidationError('oauth_consumer_key не строка')
    outcome_url = params.get('lis_outcome_service_url')
    if outcome_url is not None and not isinstance(outcome_url, str):
        raise ValidationError('lis_outcome_service_url не строка')

    is_correct = _parse_is_correct(record.get('is_correct'))
    if attempt_type == 'run' and is_correct is not None:
        raise ValidationError(
            "для attempt_type='run' is_correct должен быть NULL, "
            f"получено {record.get('is_correct')!r}")

    return Attempt(
        user_id=_required_text(record.get('lti_user_id'), 'lti_user_id'),
        oauth_consumer_key=(consumer_key or '').strip() or None,
        lis_result_sourcedid=_required_text(
            params.get('lis_result_sourcedid'), 'lis_result_sourcedid'),
        lis_outcome_service_url=(outcome_url or '').strip() or None,
        is_correct=is_correct,
        attempt_type=attempt_type,
        created_at=_parse_created_at(record.get('created_at')),
    )


def transform(records):
    """Обрабатывает все записи. Возвращает (корректные Attempt, число пропущенных).

    Каждая пропущенная запись попадает в лог с номером и причиной.
    """
    attempts = []
    skipped = 0
    for index, record in enumerate(records):
        try:
            attempts.append(parse_record(record))
        except ValidationError as exc:
            skipped += 1
            log.warning('Запись #%d пропущена: %s', index, exc)
    without_url = sum(1 for a in attempts if a.lis_outcome_service_url is None)
    log.info('Обработка завершена: корректных %d, пропущено %d, '
             'из корректных без lis_outcome_service_url %d (сохранены с NULL)',
             len(attempts), skipped, without_url)
    return attempts, skipped
