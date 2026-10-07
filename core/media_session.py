"""
Чтение текущего медиа из Windows Media Session API (SMTC).
Работает только на Windows 10/11.
"""

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger('yt-local.media_session')


@dataclass
class NowPlaying:
    """Текущий медиа-сеанс."""
    title: str
    artist: str
    album: str
    app_name: str
    is_playing: bool
    position_ms: int
    duration_ms: int
    video_id: str | None = None   # заполняется позже из Tampermonkey


# Кэш для AUMID браузеров (ищем один раз, потом переиспользуем)
_cached_browser_aumid: str | None = None


async def _find_browser_aumid() -> str | None:
    """Ищет AUMID активного браузера среди медиа-сессий."""
    global _cached_browser_aumid
    if _cached_browser_aumid:
        return _cached_browser_aumid

    try:
        from py_now_playing import PyNowPlaying
    except ImportError:
        logger.error("py-now-playing не установлен")
        return None

    try:
        ids = await PyNowPlaying.get_active_app_user_model_ids()
        browser_keywords = ('chrome', 'edge', 'vivaldi', 'firefox', 'brave', 'opera')

        for app in ids:
            name = app.get('Name', '').lower()
            if any(kw in name for kw in browser_keywords):
                _cached_browser_aumid = app['AppID']
                logger.info(f"Найден браузер: {app['Name']} ({app['AppID']})")
                return _cached_browser_aumid
    except Exception as e:
        logger.warning(f"Ошибка поиска AUMID: {e}")

    return None


async def get_current_media() -> NowPlaying | None:
    """
    Возвращает текущий медиа-сеанс браузера или None.
    """
    try:
        from py_now_playing import PyNowPlaying
    except ImportError:
        return None

    aumid = await _find_browser_aumid()
    if not aumid:
        return None

    try:
        pnp = await PyNowPlaying.create(aumid=aumid)
        media = await pnp.get_media_info()

        if not media.title:
            return None

        # PlaybackInfo.playback_status: 4 = Playing (по документации WinRT)
        try:
            playback = await pnp.get_playback_info()
            is_playing = playback.playback_status == 4
        except Exception:
            is_playing = True

        # Timeline
        position_ms = 0
        duration_ms = 0
        try:
            timeline = await pnp.get_timeline_properties()
            if timeline.position:
                position_ms = int(timeline.position.total_seconds() * 1000)
            if timeline.end_time:
                duration_ms = int(timeline.end_time.total_seconds() * 1000)
        except Exception:
            pass

        return NowPlaying(
            title=media.title,
            artist=media.artist or '',
            album=media.album or '',
            app_name='browser',
            is_playing=is_playing,
            position_ms=position_ms,
            duration_ms=duration_ms,
        )
    except Exception as e:
        logger.debug(f"Media Session недоступен: {e}")
        return None