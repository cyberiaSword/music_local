"""Контроллеры пользовательского интерфейса."""

from ui.controllers.download_controller import DownloadController
from ui.controllers.lyrics_controller import LyricsController
from ui.controllers.player_controller import PlayerController
from ui.controllers.track_controller import TrackController

__all__ = [
    "DownloadController",
    "LyricsController",
    "PlayerController",
    "TrackController",
]
