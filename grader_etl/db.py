"""Работа с локальной базой PostgreSQL."""
import logging
from datetime import datetime, timedelta

import psycopg2
from psycopg2.extras import execute_values

log = logging.getLogger(__name__)

TABLE = 'grader_attempts'

# created_at хранится как TIMESTAMP без часового пояса: время на сервере API
# всегда в UTC, и мы сохраняем его как есть.
# UNIQUE по (user_id, lis_result_sourcedid, attempt_type, created_at) делает
# загрузку идемпотентной: повторный запуск за тот же день не создает дубликатов.
SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS {TABLE} (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    oauth_consumer_key TEXT,
    lis_result_sourcedid TEXT NOT NULL,
    lis_outcome_service_url TEXT,
    is_correct BOOLEAN,
    attempt_type TEXT NOT NULL CHECK (attempt_type IN ('run', 'submit')),
    created_at TIMESTAMP NOT NULL,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT {TABLE}_uniq
        UNIQUE (user_id, lis_result_sourcedid, attempt_type, created_at)
);
CREATE INDEX IF NOT EXISTS {TABLE}_created_at_idx ON {TABLE} (created_at);
"""

INSERT_SQL = f"""
INSERT INTO {TABLE} (user_id, oauth_consumer_key, lis_result_sourcedid,
                     lis_outcome_service_url, is_correct, attempt_type, created_at)
VALUES %s
ON CONFLICT ON CONSTRAINT {TABLE}_uniq DO NOTHING
RETURNING id
"""

# lis_result_sourcedid имеет вид "курс:версия:блок:студент", например
# "course-v1:org+course+2026:lms.example-<блок>:<студент>".
# Задача - это пара "курс + блок" (2-й и 3-й сегменты), а целиком значение
# уникально для каждой пары студент-задача, поэтому считать по нему нельзя.
STATS_SQL = f"""
SELECT count(*),
       count(*) FILTER (WHERE attempt_type = 'run'),
       count(*) FILTER (WHERE attempt_type = 'submit'),
       count(*) FILTER (WHERE attempt_type = 'submit' AND is_correct),
       count(DISTINCT user_id),
       count(DISTINCT split_part(lis_result_sourcedid, ':', 2) || ':' ||
                      split_part(lis_result_sourcedid, ':', 3))
FROM {TABLE}
WHERE created_at >= %s AND created_at < %s
"""


def connect(settings):
    return psycopg2.connect(
        host=settings.pg_host, port=settings.pg_port, dbname=settings.pg_db,
        user=settings.pg_user, password=settings.pg_password or None)


def init_schema(conn):
    with conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)
    conn.commit()


def insert_attempts(conn, attempts, page_size=1000):
    """Пишет попытки в таблицу. Возвращает число реально добавленных строк."""
    if not attempts:
        return 0
    rows = [(a.user_id, a.oauth_consumer_key, a.lis_result_sourcedid,
             a.lis_outcome_service_url, a.is_correct, a.attempt_type, a.created_at)
            for a in attempts]
    try:
        with conn.cursor() as cur:
            inserted = execute_values(cur, INSERT_SQL, rows,
                                      page_size=page_size, fetch=True)
        conn.commit()
    except psycopg2.Error:
        conn.rollback()
        raise
    return len(inserted)


def daily_stats(conn, day):
    """Агрегаты за календарные сутки day (UTC) по данным из базы."""
    day_start = datetime.combine(day, datetime.min.time())
    with conn.cursor() as cur:
        cur.execute(STATS_SQL, (day_start, day_start + timedelta(days=1)))
        total, runs, submits, correct, users, tasks = cur.fetchone()
    return {
        'date': day.isoformat(),
        'total_attempts': total,
        'run_attempts': runs,
        'submit_attempts': submits,
        'correct_submits': correct,
        'success_rate': round(correct / submits * 100, 2) if submits else 0.0,
        'unique_users': users,
        'unique_tasks': tasks,
    }
