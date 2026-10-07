"""
Fallback: парсинг заголовка окна браузера.
Не даёт video_id, но даёт title.
"""

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger('yt-local.window_parser')


@dataclass
class WindowInfo:
    title: str
    app_name: str
    is_youtube: bool


# Браузеры, которые ищем в заголовке окна
BROWSER_PROCESSES = ('vivaldi', 'chrome', 'firefox', 'edge', 'brave', 'opera')

# Паттерны заголовка YouTube
YOUTUBE_PATTERNS = [
    re.compile(r'^(?P<title>.+?)\s*-\s*YouTube$', re.IGNORECASE),
    re.compile(r'^(?P<title>.+?)\s*-\s*YouTube Music$', re.IGNORECASE),
]


def get_active_browser_window() -> WindowInfo | None:
    """
    Возвращает заголовок активного окна браузера.
    Не даёт video_id — только title.
    """
    try:
        import pygetwindow as gw
    except ImportError:
        logger.error("pygetwindow не установлен")
        return None

    try:
        # Пробуем активное окно
        active = gw.getActiveWindow()
        if active and active.title:
            title = active.title
            # Определяем, браузер ли это
            for browser in BROWSER_PROCESSES:
                if browser in title.lower():
                    return WindowInfo(
                        title=title,
                        app_name=browser,
                        is_youtube='youtube' in title.lower(),
                    )
            # Если активное окно — браузер, но без слова youtube
            # (вдруг пользователь свернул окно и смотрит статус)
            if any(b in title.lower() for b in ('youtube', 'youtu')):
                return WindowInfo(
                    title=title,
                    app_name='browser',
                    is_youtube=True,
                )

        # Если активное окно не браузер — ищем любое окно с YouTube
        for w in gw.getWindowsWithTitle('YouTube'):
            if w.title and w.title != 'YouTube':
                return WindowInfo(
                    title=w.title,
                    app_name='browser',
                    is_youtube=True,
                )
    except Exception as e:
        logger.debug(f"Ошибка парсинга окна: {e}")

    return None


def extract_youtube_title(window_title: str) -> str | None:
    """Извлекает название видео из заголовка окна."""
    for pattern in YOUTUBE_PATTERNS:
        m = pattern.match(window_title)
        if m:
            return m.group('title').strip()
    return None