import logging
from datetime import date

from grader_etl.logger_setup import remove_old_logs, setup_logging

TODAY = date(2026, 10, 30)


def make_logs(log_dir, names):
    for name in names:
        (log_dir / name).write_text('x', encoding='utf-8')


def test_keeps_only_last_three_days(tmp_path):
    make_logs(tmp_path, ['2026-10-26.log', '2026-10-27.log', '2026-10-28.log',
                         '2026-10-29.log', '2026-10-30.log'])
    removed = remove_old_logs(tmp_path, keep_days=3, today=TODAY)
    assert sorted(p.name for p in removed) == ['2026-10-26.log', '2026-10-27.log']
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        '2026-10-28.log', '2026-10-29.log', '2026-10-30.log']


def test_foreign_files_are_not_touched(tmp_path):
    make_logs(tmp_path, ['notes.txt', 'app.log', '2026-13-45.log', '2020-01-01.log'])
    remove_old_logs(tmp_path, keep_days=3, today=TODAY)
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        '2026-13-45.log', 'app.log', 'notes.txt']


def test_setup_logging_writes_dated_file(tmp_path, clean_logging):
    make_logs(tmp_path, ['2026-10-01.log'])
    log_file = setup_logging(tmp_path, keep_days=3, today=TODAY)
    logging.getLogger('test').info('проверка записи')
    for handler in logging.getLogger().handlers:
        handler.flush()

    assert log_file.name == '2026-10-30.log'
    text = log_file.read_text(encoding='utf-8')
    assert 'проверка записи' in text
    assert 'INFO' in text and 'test' in text
    assert not (tmp_path / '2026-10-01.log').exists()
