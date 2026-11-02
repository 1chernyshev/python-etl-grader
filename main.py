"""Точка входа: статистика грейдера -> PostgreSQL -> Google Sheets и почта.

Примеры:
    python main.py                      # за вчерашние сутки (UTC)
    python main.py --date 2026-05-31    # за указанные сутки
    python main.py --start "2026-05-30 00:00:00" --end "2026-05-31 23:59:59"
"""
import argparse
import logging
import sys
import time
from datetime import date, datetime, time as dt_time, timedelta, timezone

from grader_etl import api_client, db, notify, sheets, transform
from grader_etl.config import LOG_DIR, LOG_KEEP_DAYS, load_settings
from grader_etl.logger_setup import setup_logging

log = logging.getLogger('main')


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--date', type=date.fromisoformat,
                        help='сутки ГГГГ-ММ-ДД (по умолчанию вчера)')
    parser.add_argument('--start', help='начало интервала, ГГГГ-ММ-ДД ЧЧ:ММ:СС')
    parser.add_argument('--end', help='конец интервала, ГГГГ-ММ-ДД ЧЧ:ММ:СС')
    parser.add_argument('--no-sheets', action='store_true',
                        help='не выгружать статистику в Google Sheets')
    parser.add_argument('--no-email', action='store_true',
                        help='не отправлять письмо')
    return parser.parse_args(argv)


def resolve_range(args, today=None):
    """Определяет интервал загрузки: (начало, конец)."""
    if args.start or args.end:
        if not (args.start and args.end):
            raise ValueError('Параметры --start и --end нужно указывать вместе')
        start, end = api_client.parse_dt(args.start), api_client.parse_dt(args.end)
    else:
        utc_today = today or datetime.now(timezone.utc).date()
        day = args.date or (utc_today - timedelta(days=1))
        start = datetime.combine(day, dt_time.min)
        end = datetime.combine(day, dt_time.max)
    if start > end:
        raise ValueError('Начало интервала позже конца')
    return start, end


def load_data(settings, start, end):
    """Скачивает, обрабатывает и загружает данные. Возвращает счетчики."""
    totals = {'downloaded': 0, 'valid': 0, 'skipped': 0, 'inserted': 0}
    conn = db.connect(settings)
    try:
        db.init_schema(conn)
        for chunk_start, chunk_end in api_client.split_into_days(start, end):
            records = api_client.fetch_statistics(settings, chunk_start, chunk_end)
            attempts, skipped = transform.transform(records)

            log.info('Заполнение базы началось: %d записей', len(attempts))
            started = time.monotonic()
            inserted = db.insert_attempts(conn, attempts)
            log.info('Заполнение базы завершено: добавлено %d, уже были в базе %d, за %.1f с',
                     inserted, len(attempts) - inserted, time.monotonic() - started)

            totals['downloaded'] += len(records)
            totals['valid'] += len(attempts)
            totals['skipped'] += skipped
            totals['inserted'] += inserted

        days = sorted({chunk[0].date() for chunk in api_client.split_into_days(start, end)})
        stats = [db.daily_stats(conn, day) for day in days]
    finally:
        conn.close()
    return totals, stats


def build_email_body(start, end, totals, stats, elapsed, warnings):
    lines = [
        f'Интервал: {start} - {end} (UTC)',
        f'Скачано записей: {totals["downloaded"]}',
        f'Корректных: {totals["valid"]}, пропущено: {totals["skipped"]}',
        f'Добавлено в базу: {totals["inserted"]}',
        f'Время работы: {elapsed:.1f} с',
        '',
        'Статистика по дням:',
    ]
    for item in stats:
        lines.append(
            f'  {item["date"]}: попыток {item["total_attempts"]}, '
            f'успешных сабмитов {item["correct_submits"]} из {item["submit_attempts"]} '
            f'({item["success_rate"]}%), уникальных студентов {item["unique_users"]}')
    if warnings:
        lines += ['', 'Предупреждения:'] + [f'  {text}' for text in warnings]
    return '\n'.join(lines)


def main(argv=None):
    args = parse_args(argv)
    log_file = setup_logging(LOG_DIR, LOG_KEEP_DAYS)
    started = time.monotonic()
    log.info('Скрипт запущен, лог: %s', log_file.name)
    settings = None
    warnings = []

    try:
        settings = load_settings()
        start, end = resolve_range(args)
        totals, stats = load_data(settings, start, end)
    except Exception as exc:
        log.exception('Скрипт завершился с ошибкой')
        if settings and not args.no_email:
            notify.send_email(settings, 'Грейдер ETL: ошибка',
                              f'Скрипт завершился с ошибкой: {exc}\nПодробности в логе.')
        return 1

    if not args.no_sheets:
        if settings.sheets_spreadsheet_id and settings.sheets_key_path.exists():
            try:
                sheets.upload_daily_stats(stats, settings.sheets_key_path,
                                          settings.sheets_spreadsheet_id)
            except Exception as exc:
                log.exception('Не удалось выгрузить статистику в Google Sheets')
                warnings.append(f'Google Sheets: {exc}')
        else:
            log.warning('Google Sheets не настроен, выгрузка пропущена')

    elapsed = time.monotonic() - started
    log.info('Скрипт завершен за %.1f с', elapsed)
    if not args.no_email:
        notify.send_email(settings, f'Грейдер ETL: {start:%Y-%m-%d} - успешно',
                          build_email_body(start, end, totals, stats, elapsed, warnings))
    return 0


if __name__ == '__main__':
    sys.exit(main())
