"""
Хранилище пользовательских настроек (JSON).
Все параметры приложения хранятся здесь.
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger('yt-local.settings')


DEFAULTS: dict[str, Any] = {
    # Пути
    "downloads_dir": "data/downloads",
    "covers_dir": "data/covers",

    # Формат аудио
    "audio_format": "mp3",           # mp3 | opus
    "audio_quality_v0": True,        # True = V0 (~245 kbps), False = V2 (~190 kbps)

    # Обложки
    "cover_mode": "auto",            # poster | video_frame | auto
    "video_frame_second": 15,        # секунда, с которой берём кадр
    "cover_size_list": "hqdefault",  # hqdefault | mqdefault | maxresdefault
    "cover_size_player": "maxresdefault",

    # Автоскачивание
    "auto_download": True,
    "max_concurrent_downloads": 1,   # пока поддерживаем только 1

    # Плеер
    "player_volume": 70,             # 0..100
    "player_autoplay_next": True,

    # Оптимизатор
    "optimize_threshold_kbps": 250,

    # UI
    "window_geometry": None,         # base64 QByteArray
    "window_state": None,            # base64 QByteArray
    "minimize_to_tray": True,
    "start_minimized": False,

    # WebSocket
    "ws_host": "127.0.0.1",
    "ws_port": 8765,

    # Прокси для yt-dlp (Clash Verge, VPN, etc.)
    "proxy": "http://127.0.0.1:7897",
}


class Settings:
    """Простое JSON-хранилище настроек."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, Any] = {}
        self.load()

    def load(self) -> None:
        if self.path.exists():
            try:
                with open(self.path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                self._data = {**DEFAULTS, **loaded}
            except (json.JSONDecodeError, OSError) as e:
                logger.error(f"Не удалось прочитать {self.path}: {e}")
                self._data = dict(DEFAULTS)
        else:
            self._data = dict(DEFAULTS)
            self.save()

    def save(self) -> None:
        try:
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except OSError as e:
            logger.error(f"Не удалось сохранить {self.path}: {e}")

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, DEFAULTS.get(key, default))

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def __getitem__(self, key: str) -> Any:
        return self.get(key)

    def __setitem__(self, key: str, value: Any) -> None:
        self.set(key, value)