"""
Единый маппинг статусов загрузки → иконка + цвет + подпись.
"""

from PyQt6.QtGui import QIcon
from ui.icons import get_pixmap, get_icon
from ui.styles import COLORS


STATUS_MAP = {
    'pending':     ('clock',        COLORS['text_muted'],   'В очереди'),
    'downloading': ('loader',       COLORS['accent_blue'],  'Скачивается'),
    'done':        ('check-circle', COLORS['accent_green'], 'Скачано'),
    'failed':      ('x-circle',     COLORS['accent_red'],   'Ошибка'),
    'skipped':     ('x-circle',     COLORS['text_muted'],   'Пропущено'),
}


def get_status_icon(status: str, size: int = 16) -> QIcon:
    """Возвращает QIcon для статуса."""
    name, color, _ = STATUS_MAP.get(status, ('clock', COLORS['text_muted'], '?'))
    return get_icon(name, size, color)


def get_status_pixmap(status: str, size: int = 16):
    """Возвращает QPixmap для статуса (для отрисовки вручную)."""
    name, color, _ = STATUS_MAP.get(status, ('clock', COLORS['text_muted'], '?'))
    return get_pixmap(name, size, color)


def get_status_color(status: str) -> str:
    _, color, _ = STATUS_MAP.get(status, ('clock', COLORS['text_muted'], '?'))
    return color


def get_status_label(status: str) -> str:
    _, _, label = STATUS_MAP.get(status, ('clock', COLORS['text_muted'], status))
    return label