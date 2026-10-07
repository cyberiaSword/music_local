"""
Единый наблюдатель за воспроизведением.
Гибрид: Media Session (основной) + Window Parser (fallback).
"""

import asyncio
import logging
from dataclasses import dataclass

from PyQt6.QtCore import QThread, pyqtSignal

from core.media_session import get_current_media, NowPlaying
from core.window_parser import get_active_browser_window, extract_youtube_title

logger = logging.getLogger('yt-local.media_watcher')


@dataclass
class DetectedTrack:
    """Обнаруженный трек (объединённые данные)."""
    title: str
    artist: str
    album: str
    duration_ms: int
    source: str          # 'media_session' | 'window_parser'
    video_id: str | None = None


class MediaWatcher(QThread):
    """
    Поток-демон: следит за воспроизведением в браузере.
    Эмитит track_detected, когда начинается новый трек.
    """

    track_detected = pyqtSignal(object)   # DetectedTrack
    state_changed = pyqtSignal(bool)      # is_playing
    error = pyqtSignal(str)

    POLL_INTERVAL_MS = 2000

    def __init__(self, parent=None):
        super().__init__(parent)
        self._stop = False
        self._last_title: str | None = None
        self._last_is_playing: bool = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        logger.info("MediaWatcher запущен")

        while not self._stop:
            try:
                track = loop.run_until_complete(self._detect())
            except Exception as e:
                logger.exception(f"Ошибка MediaWatcher: {e}")
                track = None

            if track:
                self._handle_track(track)

            self.msleep(self.POLL_INTERVAL_MS)

        loop.close()
        logger.info("MediaWatcher остановлен")

    async def _detect(self) -> DetectedTrack | None:
        """Пытается получить трек из двух источников."""
        # 1. Media Session (основной)
        now_playing = await get_current_media()
        if now_playing and now_playing.title and now_playing.is_playing:
            return DetectedTrack(
                title=now_playing.title,
                artist=now_playing.artist,
                album=now_playing.album,
                duration_ms=now_playing.duration_ms,
                source='media_session',
            )

        # 2. Window Parser (fallback)
        window = get_active_browser_window()
        if window and window.is_youtube:
            title = extract_youtube_title(window.title)
            if title:
                return DetectedTrack(
                    title=title,
                    artist='',
                    album='',
                    duration_ms=0,
                    source='window_parser',
                )

        return None

    def _handle_track(self, track: DetectedTrack) -> None:
        """Сравнивает с предыдущим состоянием и эмитит сигнал при смене."""
        # Смена трека по title
        if track.title != self._last_title:
            self._last_title = track.title
            logger.info(f"Обнаружен трек [{track.source}]: {track.title}")
            self.track_detected.emit(track)