"""Клиент API статистики грейдера."""
import logging
import re
import time
from datetime import datetime, time as dt_time, timedelta
from urllib.parse import quote, quote_plus

import requests

from .timeutil import to_utc_naive

log = logging.getLogger(__name__)

API_DT_FORMAT = '%Y-%m-%d %H:%M:%S.%f'


class ApiError(Exception):
    """API недоступен или вернул данные неожиданного вида."""


def parse_dt(text):
    """Разбирает дату или дату-время и приводит к наивному UTC.

    Время на сервере API в UTC; значение со смещением пересчитывается в UTC,
    без смещения считается UTC. Так интервал можно резать на сутки без ошибки
    сравнения наивных и осведомленных дат.
    """
    return to_utc_naive(datetime.fromisoformat(text))


def split_into_days(start, end):
    """Режет интервал на куски в пределах одних суток: (начало, конец)."""
    chunks = []
    day = start.date()
    while day <= end.date():
        chunk_start = max(start, datetime.combine(day, dt_time.min))
        chunk_end = min(end, datetime.combine(day, dt_time.max))
        chunks.append((chunk_start, chunk_end))
        day += timedelta(days=1)
    return chunks


def _redact(text, settings):
    """Прячет ключ клиента, чтобы он не попал в лог.

    requests пишет в текст ошибки URL с ключом в URL-кодировке, поэтому
    скрываем и исходный вид, и закодированные варианты, а параметр client_key
    дополнительно вырезаем целиком.
    """
    result = str(text)
    key = settings.api_client_key
    for variant in {key, quote(key, safe=''), quote_plus(key)}:
        if variant:
            result = result.replace(variant, '***')
    return re.sub(r"(client_key=)[^&\s'\")]*", r'\1***', result)


def fetch_statistics(settings, start, end, retries=3, timeout=120, sleep=time.sleep):
    """Скачивает попытки студентов за интервал [start, end].

    Ошибки сети и ответы 5xx/429 повторяются (до retries попыток),
    остальные статусы сразу приводят к ApiError. Все ошибки пишутся в лог.
    """
    params = {
        'client': settings.api_client,
        'client_key': settings.api_client_key,
        'start': start.strftime(API_DT_FORMAT),
        'end': end.strftime(API_DT_FORMAT),
    }
    log.info('Скачивание началось: %s - %s', params['start'], params['end'])
    started = time.monotonic()

    for attempt in range(1, retries + 1):
        try:
            response = requests.get(settings.api_url, params=params, timeout=timeout)
        except requests.RequestException as exc:
            log.error('Ошибка соединения с API (попытка %d из %d): %s',
                      attempt, retries, _redact(exc, settings))
        else:
            if response.status_code == 200:
                try:
                    data = response.json()
                except ValueError:
                    log.error('Ответ API не является JSON (попытка %d из %d)',
                              attempt, retries)
                else:
                    if not isinstance(data, list):
                        raise ApiError(
                            f'Ожидался список записей, получен {type(data).__name__}')
                    log.info('Скачивание завершено: %d записей за %.1f с',
                             len(data), time.monotonic() - started)
                    return data
            else:
                log.error('Ошибка доступа к API: status_code=%s, ответ: %.200s',
                          response.status_code, _redact(response.text, settings))
                if response.status_code < 500 and response.status_code != 429:
                    raise ApiError(f'API вернул status_code={response.status_code}')
        if attempt < retries:
            sleep(2 ** attempt)

    raise ApiError(f'API недоступен после {retries} попыток')
