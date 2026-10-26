"""Контроллер панели текста и загрузки текста в отдельном потоке."""

import logging

from PyQt6.QtCore import QObject, QThread, pyqtSignal

from core.lyrics import fetch_lyrics

logger = logging.getLogger("yt-local.ui.lyrics_controller")


class LyricsWorker(QThread):
    loaded = pyqtSignal(str, object)

    def __init__(self, track, lyrics_dir, parent=None):
        super().__init__(parent)
        self.video_id = track.video_id
        self.title = track.title
        self.artist = track.channel or ""
        self.duration = track.duration or 0
        self.lyrics_dir = lyrics_dir

    def run(self) -> None:
        if self.isInterruptionRequested():
            return
        try:
            data = fetch_lyrics(
                title=self.title,
                artist=self.artist,
                duration_sec=self.duration,
                lyrics_dir=self.lyrics_dir,
                video_id=self.video_id,
            )
        except Exception:
            logger.exception("Не удалось загрузить текст песни")
            data = None
        if not self.isInterruptionRequested():
            self.loaded.emit(self.video_id, data)


class LyricsController(QObject):
    def __init__(self, player, player_widget, lyrics_panel, lyrics_dir, parent=None):
        super().__init__(parent)
        self.player = player
        self.player_widget = player_widget
        self.lyrics_panel = lyrics_panel
        self.lyrics_dir = lyrics_dir
        self._is_synced = False
        self._workers: set[LyricsWorker] = set()

        player.track_changed.connect(self.load_for_track)
        player.position_changed.connect(self.update_position)
        player_widget.lyrics_toggled.connect(self.set_visible)
        lyrics_panel.closed.connect(self.close)

    def set_visible(self, visible: bool) -> None:
        self.lyrics_panel.setVisible(visible)
        track = self.player.current_track()
        if visible and track is not None:
            self.load_for_track(track)

    def close(self) -> None:
        self.lyrics_panel.setVisible(False)
        self.player_widget.btn_lyrics.setChecked(False)

    def load_for_track(self, track) -> None:
        if not self.lyrics_panel.isVisible():
            return

        worker = LyricsWorker(track, self.lyrics_dir, self)
        worker.loaded.connect(self._on_loaded)
        worker.finished.connect(lambda current=worker: self._workers.discard(current))
        self._workers.add(worker)
        worker.start()

    def _on_loaded(self, video_id: str, data) -> None:
        track = self.player.current_track()
        if track is None or track.video_id != video_id:
            return
        self._is_synced = bool(data and data.is_synced)
        self.lyrics_panel.show_lyrics(data, track.title)

    def update_position(self, position_ms: int) -> None:
        if self.lyrics_panel.isVisible():
            self.lyrics_panel.update_position(position_ms, self._is_synced)

    def shutdown(self) -> None:
        for worker in tuple(self._workers):
            worker.requestInterruption()
            worker.wait()
        self._workers.clear()
