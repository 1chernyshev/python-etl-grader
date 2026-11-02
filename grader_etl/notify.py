"""Почтовые уведомления о запуске скрипта (задание с двумя звездочками)."""
import logging
import smtplib
import ssl
from email.message import EmailMessage

log = logging.getLogger(__name__)


def send_email(settings, subject, body):
    """Отправляет письмо через SMTP_SSL. Возвращает True при успехе.

    Ошибка отправки только пишется в лог: уведомление не должно ронять
    сам процесс загрузки данных.
    """
    if not (settings.smtp_user and settings.smtp_password and settings.notify_to):
        log.warning('Почта не настроена (SMTP_USER, SMTP_PASSWORD), письмо не отправлено')
        return False

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = settings.smtp_user
    msg['To'] = settings.notify_to
    msg.set_content(body)

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port,
                              context=context, timeout=30) as server:
            server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        log.error('Не удалось отправить письмо: %s', exc)
        return False
    log.info('Письмо отправлено на %s', settings.notify_to)
    return True
