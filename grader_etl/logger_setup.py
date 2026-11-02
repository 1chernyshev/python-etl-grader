"""Логирование: файл с именем по дате и очистка старых логов."""
import logging
import re
from datetime import date, timedelta
from pathlib import Path

LOG_NAME_RE = re.compile(r'^(\d{4}-\d{2}-\d{2})\.log$')
LOG_FORMAT = '%(asctime)s %(name)s %(levelname)s: %(message)s'


def remove_old_logs(log_dir, keep_days=3, today=None):
    """Удаляет логи старше keep_days дней (считая сегодняшний день).

    Остаются файлы за сегодня и за предыдущие keep_days - 1 дней.
    Файлы, имя которых не похоже на ГГГГ-ММ-ДД.log, не трогаем.
    Возвращает список удаленных файлов.
    """
    today = today or date.today()
    oldest_kept = today - timedelta(days=keep_days - 1)
    removed = []
    for path in sorted(Path(log_dir).iterdir()):
        match = LOG_NAME_RE.match(path.name)
        if not match or not path.is_file():
            continue
        try:
            log_date = date.fromisoformat(match.group(1))
        except ValueError:
            continue
        if log_date < oldest_kept:
            path.unlink()
            removed.append(path)
    return removed


def setup_logging(log_dir, keep_days=3, today=None):
    """Настраивает корневой логгер: вывод в консоль и в файл ГГГГ-ММ-ДД.log.

    Возвращает путь к файлу сегодняшнего лога.
    """
    today = today or date.today()
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    removed = remove_old_logs(log_dir, keep_days, today)

    log_file = log_dir / f'{today:%Y-%m-%d}.log'
    formatter = logging.Formatter(LOG_FORMAT)
    file_handler = logging.FileHandler(log_file, encoding='utf-8')
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.addHandler(file_handler)
    root.addHandler(console_handler)

    if removed:
        logging.getLogger(__name__).info(
            'Удалены старые логи: %s', ', '.join(path.name for path in removed))
    return log_file
