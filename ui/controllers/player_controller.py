"""Контроллер команд плеера и синхронизации активного трека."""

import logging
import sqlite3
from typing import Literal

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from core.database import Track
from core.settings import Settings

logger = logging.getLogger('yt-local.queue')


class PlayerController(QObject):
    toast_requested = pyqtSignal(str)
    queue_changed = pyqtSignal(list, int)

    def __init__(self, player, track_controller, status_bar, parent=None,
                 *, settings: Settings | None = None):
        super().__init__(parent)
        self.player = player
        self.track_controller = track_controller
        self.status_bar = status_bar
        self.settings = settings
        self._queue_ids: list[int] = []
        self._queue_tracks: list[Track] = []
        self.current_index = -1
        self._saved_state: tuple | None = None

        player.track_changed.connect(self._on_track_changed)
        player.error_occurred.connect(self._on_error)
        player.queue_changed.connect(self._on_queue_changed)
        player.queue_index_changed.connect(self._on_queue_index)
        player.state_changed.connect(self._on_state_changed)
        self._restore_queue()

    @property
    def queue_ids(self) -> list[int]:
        return list(self._queue_ids)

    @property
    def queue_tracks(self) -> list[Track]:
        return list(self._queue_tracks)

    def _restore_queue(self) -> None:
        if self.settings is None:
            return
        saved = self.settings.get('queue_track_ids', [])[-200:]
        selected = self.settings.get('queue_current_index', -1)
        tracks: list[Track] = []
        current = -1
        try:
            for index, track_id in enumerate(saved):
                track = self.player.db.get_track(track_id)
                if track is not None:
                    if index == selected:
                        current = len(tracks)
                    tracks.append(track)
        except sqlite3.Error as error:
            logger.warning('Не удалось восстановить очередь: %s', error)
            return
        self.player.set_queue(tracks, current)

    def _on_queue_changed(self, tracks: list[Track]) -> None:
        self._queue_tracks = list(tracks)
        self._queue_ids = [track.id for track in tracks]
        self.current_index = self.player.queue_index
        self._publish_queue()

    def _on_queue_index(self, index: int) -> None:
        self.current_index = index
        self._publish_queue()

    def _on_state_changed(self, _state: str) -> None:
        if self.player.current_track() is None:
            self.track_controller.set_playing('')
        self._publish_queue()

    def _publish_queue(self) -> None:
        playing = self.current_index if self.player.current_track() is not None else -1
        self.queue_changed.emit(self.queue_tracks, playing)
        if self.settings is None:
            return
        offset = max(0, len(self._queue_ids) - 200)
        selected = self.current_index - offset if self.current_index >= offset else -1
        state = (tuple(self._queue_ids[offset:]), selected)
        if state != self._saved_state:
            self.settings.set('queue_track_ids', list(state[0]))
            self.settings.set('queue_current_index', selected)
            self.settings.save()
            self._saved_state = state

    def enqueue(self, track_id: int, position: Literal['end', 'next'] = 'end') -> None:
        if position not in ('end', 'next'):
            raise ValueError('Неизвестная позиция очереди')
        try:
            track = self.player.db.get_track(track_id)
        except sqlite3.Error as error:
            self._on_error(f'Не удалось добавить трек в очередь: {error}')
            return
        if track is None:
            return
        tracks = self.queue_tracks
        index = self.current_index + 1 if position == 'next' else len(tracks)
        tracks.insert(index, track)
        self.player.set_queue(tracks, self.current_index,
                              next_index=index if position == 'next' else None)

    def remove_from_queue(self, index: int) -> None:
        if not 0 <= index < len(self._queue_ids):
            return
        tracks = self.queue_tracks
        tracks.pop(index)
        current = self.current_index
        if index == current:
            self.player.stop()
            current = -1
        elif index < current:
            current -= 1
        self.player.set_queue(tracks, current)

    def clear_queue(self) -> None:
        self.player.stop()
        self.player.set_queue([], -1)

    def move_in_queue(self, from_idx: int, to_idx: int) -> None:
        self._move_in_queue(from_idx, to_idx)

    def _move_in_queue(self, from_idx: int, to_idx: int, *, play_next: bool = False) -> None:
        if not (0 <= from_idx < len(self._queue_ids) and 0 <= to_idx < len(self._queue_ids)):
            return
        order = list(range(len(self._queue_ids)))
        order.insert(to_idx, order.pop(from_idx))
        current = order.index(self.current_index) if self.current_index >= 0 else -1
        tracks = [self._queue_tracks[index] for index in order]
        self.player.set_queue(tracks, current, next_index=to_idx if play_next else None)

    def play_next(self, index: int) -> None:
        if index == self.current_index:
            return
        target = self.current_index + 1 - int(index < self.current_index)
        self._move_in_queue(index, target, play_next=True)

    def play_queue_index(self, index: int) -> None:
        self.player.play_queue_index(index)

    def play_tracks(self, tracks: list[Track], track: Track) -> None:
        """Явный запуск подборки заменяет очередь, обычный клик её сохраняет."""
        self.player.play_track(track, queue=tracks)

    def play_track(self, track: Track) -> None:
        if not self._queue_ids:
            queue = self.track_controller.build_queue()
            if not any(item.id == track.id for item in queue):
                queue = [track, *queue]
            self.player.play_track(track, queue=queue)
            return
        if track.id not in self._queue_ids:
            self.enqueue(track.id)
        if track.id not in self._queue_ids:
            return
        index = (self.current_index if 0 <= self.current_index < len(self._queue_ids)
                 and self._queue_ids[self.current_index] == track.id
                 else self._queue_ids.index(track.id))
        if self.player.play_queue_index(index):
            self.status_bar.showMessage(f"Воспроизведение: {track.title}", 5000)

    def resume_track(self) -> None:
        self.player.save_playback_state()
        state = self.player.db.get_playback_state()
        if state is None:
            return
        track, position_ms = state
        if self._queue_ids:
            if track.id not in self._queue_ids:
                self.enqueue(track.id, 'next')
            if track.id not in self._queue_ids:
                return
            index = (self.current_index if 0 <= self.current_index < len(self._queue_ids)
                     and self._queue_ids[self.current_index] == track.id
                     else self._queue_ids.index(track.id))
            self.player.set_queue(self.queue_tracks, index)
            started = self.player.play_track(track, position_ms=position_ms)
        else:
            queue = self.track_controller.build_queue()
            if not any(item.id == track.id for item in queue):
                queue = [track, *queue]
            started = self.player.play_track(track, queue=queue, position_ms=position_ms)
        if started:
            self.status_bar.showMessage(f"Продолжаем: {track.title}", 5000)

    @pyqtSlot()
    def play_pause(self) -> None:
        if self.player.current_track() is None and self._queue_ids:
            self.play_queue_index(max(0, self.current_index))
        else:
            self.player.play_pause()

    @pyqtSlot()
    def next_track(self) -> None:
        self.player.next_track()

    @pyqtSlot()
    def prev_track(self) -> None:
        self.player.prev_track()

    @pyqtSlot()
    def stop(self) -> None:
        self.player.stop()
        self.track_controller.set_playing("")

    def _on_track_changed(self, track: Track) -> None:
        self.current_index = self.player.queue_index
        self._queue_tracks = [track if item.id == track.id else item
                              for item in self._queue_tracks]
        self.track_controller.set_playing(track.video_id)
        self._publish_queue()
        self.toast_requested.emit(f"Сейчас играет: {track.title}")

    def _on_error(self, message: str) -> None:
        self.status_bar.showMessage(message, 8000)
        self.toast_requested.emit(message)
