"""Время в проекте: везде наивное UTC (так его отдает API и так хранит база)."""
from datetime import timezone


def to_utc_naive(value):
    """Приводит datetime к наивному UTC.

    Время со смещением пересчитывается в UTC (а не просто теряет смещение),
    время без смещения считается уже UTC.
    """
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)
