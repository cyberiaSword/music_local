"""
Обёртка над QMediaPlayer + логика очереди воспроизведения.
"""
import random
import logging
from pathlib import Path

from PyQt6.QtCore import QObject, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

from core.database import Database, Track

logger = logging.getLogger('yt-local.player')


class Player(QObject):
    """
    Управляет воспроизведением аудио.

    Сигналы:
        track_changed(Track)         — начал играть новый трек
        position_changed(int)        — текущая позиция в мс
        duration_changed(int)        — длительность в мс
        state_changed(str)           — 'playing' | 'paused' | 'stopped'
        volume_changed(int)          — громкость 0..100
        error_occurred(str)          — текст ошибки
        queue_changed(list)          — очередь обновилась
        
    """

    track_changed = pyqtSignal(object)
    position_changed = pyqtSignal(int)
    duration_changed = pyqtSignal(int)
    state_changed = pyqtSignal(str)
    volume_changed = pyqtSignal(int)
    error_occurred = pyqtSignal(str)
    queue_changed = pyqtSignal(list)
    shuffle_changed = pyqtSignal(bool)
    repeat_changed = pyqtSignal(str)

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db

        self._player = QMediaPlayer()
        self._audio = QAudioOutput()
        self._player.setAudioOutput(self._audio)

        self._current_track: Track | None = None
        self._queue: list[Track] = []
        self._queue_index: int = -1
        self._autoplay_next: bool = True

        # Подписка на события QMediaPlayer
        self._player.positionChanged.connect(self.position_changed.emit)
        self._player.durationChanged.connect(self.duration_changed.emit)
        self._player.playbackStateChanged.connect(self._on_state_changed)
        self._player.errorOccurred.connect(self._on_error)
        self._shuffle_mode: bool = False
        self._repeat_mode: str = 'off'   # 'off' | 'all' | 'one'
        self._shuffle_order: list[int] = []   # индексы в _queue в перемешанном порядке
        self._shuffle_pos: int = 0
        self.set_volume(70)

    # ============================================================
    # Воспроизведение
    # ============================================================

    def play_track(self, track: Track, queue: list[Track] | None = None) -> bool:
        """
        Начинает воспроизведение трека.
        Если queue передана — использует её для next/prev.
        Возвращает True, если удалось запустить.
        """
        file_path = self._resolve_file(track)
        if file_path is None:
            msg = f"Файл не найден для трека: {track.title}"
            logger.warning(msg)
            self.error_occurred.emit(msg)
            return False

        if queue is not None:
            self._queue = list(queue)
            try:
                self._queue_index = self._queue.index(track)
            except ValueError:
                self._queue_index = -1
            self.queue_changed.emit(self._queue)
            self._rebuild_shuffle_order()

        self._current_track = track
        self._player.setSource(QUrl.fromLocalFile(str(file_path)))
        self._player.play()
        self.track_changed.emit(track)
        logger.info(f"Воспроизведение: {track.title} ({file_path.name})")
        return True

    def play_pause(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        elif self._current_track is not None:
            self._player.play()

    def pause(self) -> None:
        self._player.pause()

    def stop(self) -> None:
        self._player.stop()
        self._current_track = None
        self.state_changed.emit('stopped')

    def next_track(self) -> None:
        """Переход к следующему треку с учётом shuffle/repeat."""
        next_idx = self._get_next_index()
        if next_idx is None:
            logger.info("Конец очереди")
            self.stop()
            return

        self._queue_index = next_idx
        self.play_track(self._queue[next_idx], queue=None)

    def prev_track(self) -> None:
        """Переход к предыдущему треку."""
        # Если прошло >3 сек — сначала перемотать в начало
        if self._player.position() > 3000:
            self._player.setPosition(0)
            return

        prev_idx = self._get_prev_index()
        if prev_idx is None:
            return

        self._queue_index = prev_idx
        self.play_track(self._queue[prev_idx], queue=None)

    def seek(self, position_ms: int) -> None:
        self._player.setPosition(position_ms)

    def set_volume(self, volume: int) -> None:
        volume = max(0, min(100, volume))
        self._audio.setVolume(volume / 100.0)
        self.volume_changed.emit(volume)

    def get_volume(self) -> int:
        return int(self._audio.volume() * 100)

    def set_autoplay_next(self, enabled: bool) -> None:
        self._autoplay_next = enabled

    # ============================================================
    # Состояние
    # ============================================================

    def current_track(self) -> Track | None:
        return self._current_track

    def is_playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def position(self) -> int:
        return self._player.position()

    def duration(self) -> int:
        return self._player.duration()

    # ============================================================
    # Внутреннее
    # ============================================================

    def _resolve_file(self, track: Track) -> Path | None:
        """Возвращает путь к MP3-файлу, если он существует."""
        if not track.file_path:
            return None

        from core.paths import get_data_dir

        path = Path(track.file_path)
        if not path.is_absolute():
            path = get_data_dir() / path
        return path if path.exists() else None

    def _on_state_changed(self, state) -> None:
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.state_changed.emit('playing')
        elif state == QMediaPlayer.PlaybackState.PausedState:
            self.state_changed.emit('paused')
        else:
            self.state_changed.emit('stopped')

        # Автопереход к следующему
                # Автопереход к следующему
        if state == QMediaPlayer.PlaybackState.StoppedState and self._current_track is not None:
            if self._player.position() >= self._player.duration() - 100:
                # Repeat one — играем тот же трек заново
                if self._repeat_mode == 'one':
                    logger.info("Повтор трека")
                    self.play_track(self._current_track, queue=None)
                    return
                # Иначе — следующий, если autoplay включён
                if self._autoplay_next:
                    logger.info("Трек закончился, переходим к следующему")
                    self.next_track()

    def _on_error(self, error, error_string: str) -> None:
        if error == QMediaPlayer.Error.NoError:
            return
        msg = f"Ошибка плеера: {error_string}"
        logger.error(msg)
        self.error_occurred.emit(msg)

        # ============================================================
    # Перемешивание
    # ============================================================

    def toggle_shuffle(self) -> bool:
        """Включает/выключает shuffle. Возвращает новое состояние."""
        self._shuffle_mode = not self._shuffle_mode
        self._rebuild_shuffle_order()
        self.shuffle_changed.emit(self._shuffle_mode)
        logger.info(f"Shuffle: {'вкл' if self._shuffle_mode else 'выкл'}")
        return self._shuffle_mode

    def is_shuffle(self) -> bool:
        return self._shuffle_mode

    def _rebuild_shuffle_order(self) -> None:
        """Пересобирает порядок воспроизведения с учётом shuffle."""
        if not self._queue:
            self._shuffle_order = []
            self._shuffle_pos = 0
            return

        indices = list(range(len(self._queue)))
        if self._shuffle_mode:
            # Текущий трек — первым, остальные перемешаны
            current = self._queue_index if self._queue_index >= 0 else 0
            others = [i for i in indices if i != current]
            random.shuffle(others)
            self._shuffle_order = [current] + others
            self._shuffle_pos = 0
        else:
            self._shuffle_order = indices
            self._shuffle_pos = max(0, self._queue_index)

    # ============================================================
    # Повтор
    # ============================================================

    def cycle_repeat(self) -> str:
        """Циклически меняет режим повтора: off → all → one → off."""
        order = ['off', 'all', 'one']
        idx = order.index(self._repeat_mode)
        self._repeat_mode = order[(idx + 1) % len(order)]
        self.repeat_changed.emit(self._repeat_mode)
        logger.info(f"Repeat: {self._repeat_mode}")
        return self._repeat_mode

    def get_repeat_mode(self) -> str:
        return self._repeat_mode

    # ============================================================
    # Next/Prev с учётом режимов
    # ============================================================

    def _get_next_index(self) -> int | None:
        """Вычисляет следующий индекс в очереди с учётом shuffle/repeat."""
        if not self._queue:
            return None

        # Shuffle
        if self._shuffle_mode:
            self._shuffle_pos += 1
            if self._shuffle_pos >= len(self._shuffle_order):
                if self._repeat_mode == 'all':
                    self._rebuild_shuffle_order()
                    self._shuffle_pos = 0
                else:
                    return None
            return self._shuffle_order[self._shuffle_pos]

        # Обычный порядок
        next_idx = self._queue_index + 1
        if next_idx >= len(self._queue):
            if self._repeat_mode == 'all':
                next_idx = 0
            else:
                return None
        return next_idx

    def _get_prev_index(self) -> int | None:
        """Вычисляет предыдущий индекс в очереди."""
        if not self._queue:
            return None

        if self._shuffle_mode:
            self._shuffle_pos -= 1
            if self._shuffle_pos < 0:
                self._shuffle_pos = len(self._shuffle_order) - 1
            return self._shuffle_order[self._shuffle_pos]

        prev_idx = self._queue_index - 1
        if prev_idx < 0:
            if self._repeat_mode == 'all':
                prev_idx = len(self._queue) - 1
            else:
                return None
        return prev_idx