"""
Загрузчик SVG-иконок из assets/icons/.
Рендерит в QPixmap нужного размера и цвета.
"""

import logging
from functools import lru_cache
from pathlib import Path

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QPixmap, QPainter, QIcon, QColor
from PyQt6.QtSvg import QSvgRenderer

logger = logging.getLogger('yt-local.icons')


# Папка с иконками — рядом с main.py
from core.paths import get_assets_dir
ICONS_DIR = get_assets_dir() / 'icons'


def _load_svg_text(name: str) -> str | None:
    """Читает текст SVG-файла."""
    path = ICONS_DIR / f"{name}.svg"
    if not path.exists():
        logger.warning(f"Иконка не найдена: {path}")
        return None
    try:
        return path.read_text(encoding='utf-8')
    except OSError as e:
        logger.error(f"Ошибка чтения иконки {name}: {e}")
        return None


@lru_cache(maxsize=512)
def get_pixmap(name: str, size: int = 24, color: str = "#ffffff") -> QPixmap:
    """
    Возвращает QPixmap с отрендеренной иконкой.
    Кэшируется по (name, size, color).
    """
    svg = _load_svg_text(name)
    if svg is None:
        # Возвращаем пустой pixmap — UI не упадёт
        p = QPixmap(size, size)
        p.fill(Qt.GlobalColor.transparent)
        return p

    # Заменяем currentColor на нужный
    svg = svg.replace('currentColor', color)

    renderer = QSvgRenderer(svg.encode('utf-8'))

    # Учитываем devicePixelRatio для Retina-дисплеев
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance()
    dpr = app.devicePixelRatio() if app else 1.0
    real_size = int(size * dpr)

    pixmap = QPixmap(real_size, real_size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    renderer.render(painter)
    painter.end()

    pixmap.setDevicePixelRatio(dpr)
    return pixmap


def get_icon(name: str, size: int = 24, color: str = "#ffffff") -> QIcon:
    """Возвращает QIcon для использования в QPushButton.setIcon()."""
    return QIcon(get_pixmap(name, size, color))


def clear_cache() -> None:
    """Очищает кэш иконок (полезно при смене темы)."""
    get_pixmap.cache_clear()