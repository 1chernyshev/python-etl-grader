"""Выгрузка дневной статистики в Google Sheets (задание со звездочкой 1)."""
import logging

import gspread

log = logging.getLogger(__name__)

WORKSHEET_TITLE = 'daily_stats'
HEADER = ['date', 'total_attempts', 'run_attempts', 'submit_attempts',
          'correct_submits', 'success_rate_pct', 'unique_users', 'unique_tasks']


def stats_to_row(stats):
    return [stats['date'], stats['total_attempts'], stats['run_attempts'],
            stats['submit_attempts'], stats['correct_submits'],
            stats['success_rate'], stats['unique_users'], stats['unique_tasks']]


def upload_daily_stats(stats_list, key_path, spreadsheet_id,
                       worksheet_title=WORKSHEET_TITLE):
    """Записывает по строке на каждый день. Строка за уже загруженный день
    обновляется, новая добавляется в конец, поэтому повторный запуск безопасен.
    """
    client = gspread.service_account(filename=str(key_path))
    spreadsheet = client.open_by_key(spreadsheet_id)
    try:
        worksheet = spreadsheet.worksheet(worksheet_title)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=worksheet_title, rows=1000, cols=len(HEADER))
    if worksheet.row_values(1) != HEADER:
        worksheet.update(values=[HEADER], range_name='A1', value_input_option='RAW')

    # RAW везде: дата остается текстом ГГГГ-ММ-ДД и не зависит от локали таблицы,
    # поэтому поиск существующей строки по дате работает одинаково при любом запуске.
    dates = worksheet.col_values(1)
    for stats in stats_list:
        row = stats_to_row(stats)
        if stats['date'] in dates:
            row_number = dates.index(stats['date']) + 1
            worksheet.update(values=[row], range_name=f'A{row_number}',
                             value_input_option='RAW')
            log.info('Google Sheets: обновлена строка за %s', stats['date'])
        else:
            worksheet.append_row(row, value_input_option='RAW')
            dates.append(stats['date'])
            log.info('Google Sheets: добавлена строка за %s', stats['date'])
