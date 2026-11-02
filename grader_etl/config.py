"""Настройки проекта: переменные окружения и файл .env."""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / 'logs'
LOG_KEEP_DAYS = 3


@dataclass(frozen=True)
class Settings:
    api_url: str
    api_client: str
    api_client_key: str
    pg_host: str
    pg_port: int
    pg_db: str
    pg_user: str
    pg_password: str
    sheets_key_path: Path
    sheets_spreadsheet_id: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    notify_to: str


def _required(name):
    value = os.environ.get(name, '').strip()
    if not value:
        raise RuntimeError(f'Не задана переменная окружения {name} (см. .env.example)')
    return value


def load_settings():
    """Читает .env из корня проекта и собирает настройки."""
    load_dotenv(BASE_DIR / '.env')
    env = os.environ.get
    key_path = Path(env('SHEETS_KEY_PATH', 'service_account.json'))
    if not key_path.is_absolute():
        key_path = BASE_DIR / key_path
    smtp_user = env('SMTP_USER', '').strip()
    return Settings(
        api_url=_required('API_URL'),
        api_client=_required('API_CLIENT'),
        api_client_key=_required('API_CLIENT_KEY'),
        pg_host=env('PG_HOST', 'localhost'),
        pg_port=int(env('PG_PORT', '5432')),
        pg_db=_required('PG_DB'),
        pg_user=_required('PG_USER'),
        pg_password=env('PG_PASSWORD', ''),
        sheets_key_path=key_path,
        sheets_spreadsheet_id=env('SHEETS_SPREADSHEET_ID', '').strip(),
        smtp_host=env('SMTP_HOST', 'smtp.gmail.com'),
        smtp_port=int(env('SMTP_PORT', '465')),
        smtp_user=smtp_user,
        smtp_password=env('SMTP_PASSWORD', ''),
        notify_to=env('NOTIFY_TO', '').strip() or smtp_user,
    )
