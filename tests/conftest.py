import logging
from pathlib import Path

import pytest

from grader_etl.config import Settings


@pytest.fixture
def settings(tmp_path):
    return Settings(
        api_url='https://api.example.test/statistics/',
        api_client='Client', api_client_key='SECRETKEY',
        pg_host='localhost', pg_port=5432, pg_db='db', pg_user='user', pg_password='',
        sheets_key_path=Path(tmp_path / 'key.json'), sheets_spreadsheet_id='sheet-id',
        smtp_host='smtp.example.test', smtp_port=465,
        smtp_user='me@example.test', smtp_password='app-password',
        notify_to='me@example.test',
    )


@pytest.fixture
def clean_logging():
    """Возвращает корневой логгер в исходное состояние после теста."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    for handler in list(root.handlers):
        handler.close()
        root.removeHandler(handler)
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(level)
