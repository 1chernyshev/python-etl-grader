import uuid
from datetime import date, datetime

import psycopg2
import pytest

from grader_etl import db
from grader_etl.config import load_settings
from grader_etl.transform import Attempt


@pytest.fixture
def conn():
    """Подключение к локальной базе; таблица создается в отдельной схеме,
    которая удаляется после теста, поэтому рабочие данные не затрагиваются."""
    try:
        connection = db.connect(load_settings())
    except (RuntimeError, psycopg2.OperationalError) as exc:
        pytest.skip(f'PostgreSQL недоступен: {exc}')
    schema = f'test_{uuid.uuid4().hex[:8]}'
    with connection.cursor() as cur:
        cur.execute(f'CREATE SCHEMA {schema}')
        cur.execute(f'SET search_path TO {schema}')
    connection.commit()
    yield connection
    connection.rollback()
    with connection.cursor() as cur:
        cur.execute(f'DROP SCHEMA {schema} CASCADE')
    connection.commit()
    connection.close()


def attempt(user='u1', task='t1', kind='run', correct=None, created=datetime(2026, 5, 31, 10, 0)):
    # реальный вид значения: курс:версия:блок:студент
    sourcedid = f'course-v1:c+X+1:lms.example-{task}:{user}'
    return Attempt(user, None, sourcedid, 'https://lms/grade', correct, kind, created)


def test_init_schema_is_idempotent(conn):
    db.init_schema(conn)
    db.init_schema(conn)


def test_insert_and_duplicates_are_skipped(conn):
    db.init_schema(conn)
    rows = [attempt(), attempt(user='u2'), attempt(user='u2')]   # последняя - дубликат
    assert db.insert_attempts(conn, rows) == 2
    assert db.insert_attempts(conn, rows) == 0                   # повторная загрузка
    assert db.insert_attempts(conn, []) == 0


def test_values_are_stored_as_is(conn):
    db.init_schema(conn)
    db.insert_attempts(conn, [attempt(kind='submit', correct=True)])
    with conn.cursor() as cur:
        cur.execute('SELECT user_id, oauth_consumer_key, is_correct, attempt_type, '
                    'created_at FROM grader_attempts')
        assert cur.fetchone() == ('u1', None, True, 'submit', datetime(2026, 5, 31, 10, 0))


def test_daily_stats(conn):
    db.init_schema(conn)
    day = datetime(2026, 5, 31, 12, 0)
    db.insert_attempts(conn, [
        attempt('u1', 't1', 'run', None, day),
        attempt('u1', 't1', 'submit', True, datetime(2026, 5, 31, 12, 5)),
        attempt('u2', 't1', 'submit', False, datetime(2026, 5, 31, 13, 0)),
        attempt('u2', 't2', 'submit', True, datetime(2026, 5, 31, 14, 0)),
        attempt('u3', 't3', 'run', None, datetime(2026, 6, 1, 0, 0, 1)),   # другой день
    ])
    stats = db.daily_stats(conn, date(2026, 5, 31))
    assert stats == {'date': '2026-05-31', 'total_attempts': 4, 'run_attempts': 1,
                     'submit_attempts': 3, 'correct_submits': 2, 'success_rate': 66.67,
                     'unique_users': 2, 'unique_tasks': 2}


def test_daily_stats_for_empty_day(conn):
    db.init_schema(conn)
    stats = db.daily_stats(conn, date(2026, 5, 31))
    assert stats['total_attempts'] == 0
    assert stats['success_rate'] == 0.0
