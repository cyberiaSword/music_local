"""
Обёртка над QMediaPlayer + логика очереди воспроизведения.
"""
import random
import logging
import sqlite3
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, QUrl, pyqtSignal
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput

from core.database import Database, Track

logger = logging.getLogger('yt-local.player')


def _friendly_media_error(error, error_string: str) -> str:
    """Возвращает понятное сообщение об ошибке декодирования или открытия файла."""
    details = error_string.lower()
    damaged_markers = (
        "corrupt", "invalid data", "truncated", "unexpected end", "failed to read"
    )
    codec_markers = ("codec", "decoder", "unsupported format", "no suitable")

    if any(marker in details for marker in damaged_markers):
        return "Аудиофайл повреждён. Скачайте трек повторно."
    if any(marker in details for marker in codec_markers):
        return "Формат аудио не поддерживается: в системе может отсутствовать кодек."
    if error == QMediaPlayer.Error.FormatError:
        return "Не удалось прочитать аудио. Файл повреждён или не поддерживается кодек."
    if error == QMediaPlayer.Error.ResourceError:
        return "Не удалось открыть аудиофайл. Проверьте, что файл доступен и не повреждён."
    if error == QMediaPlayer.Error.AccessDeniedError:
        return "Нет доступа к аудиофайлу. Проверьте разрешения для папки с музыкой."
    if error == QMediaPlayer.Error.NetworkError:
        return "Ошибка чтения аудиопотока. Проверьте сетевое соединение."
    return "Не удалось воспроизвести трек. Проверьте файл и доступность аудиокодеков."


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
    queue_index_changed = pyqtSignal(int)

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
        self._last_position_ms = 0
        self._pending_seek_ms: int | None = None
        self._changing_source = False
        self._save_timer = QTimer(self)
        self._save_timer.setInterval(5000)
        self._save_timer.timeout.connect(self.save_playback_state)
        self._save_timer.start()

        # Подписка на события QMediaPlayer
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self.duration_changed.emit)
        self._player.durationChanged.connect(self._restore_position)
        self._player.seekableChanged.connect(self._restore_position)
        self._player.mediaStatusChanged.connect(self._restore_position)
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

    def play_track(
        self, track: Track, queue: list[Track] | None = None, *, position_ms: int = 0
    ) -> bool:
        """
        Начинает воспроизведение трека с позиции в миллисекундах.
        Если queue передана — использует её для next/prev.
        Возвращает True, если удалось запустить.
        """
        file_path = self._resolve_file(track)
        if file_path is None:
            msg = f"Файл трека «{track.title}» не найден. Скачайте его повторно."
            logger.warning(msg)
            self.error_occurred.emit(msg)
            return False

        try:
            if file_path.stat().st_size == 0:
                msg = f"Файл трека «{track.title}» пуст или повреждён. Скачайте его повторно."
                logger.warning(msg)
                self.error_occurred.emit(msg)
                return False
        except OSError:
            msg = f"Не удалось прочитать файл трека «{track.title}». Проверьте доступ к файлу."
            logger.warning(msg)
            self.error_occurred.emit(msg)
            return False

        if queue is not None:
            self._queue = list(queue)
            self._queue_index = next(
                (index for index, item in enumerate(self._queue) if item.id == track.id), -1
            )
            self.queue_changed.emit(self._queue)
            self._rebuild_shuffle_order()

        self.save_playback_state()
        self._changing_source = True
        self._current_track = track
        self._last_position_ms = max(0, position_ms)
        self._pending_seek_ms = self._last_position_ms
        try:
            self._player.setSource(QUrl.fromLocalFile(str(file_path)))
        finally:
            self._changing_source = False
        self._restore_position()
        self._player.play()
        self.save_playback_state()
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
        self.save_playback_state()
        self._current_track = None
        self._pending_seek_ms = None
        self._player.stop()
        self.state_changed.emit('stopped')

    @property
    def queue_index(self) -> int:
        return self._queue_index

    def set_queue(
        self, tracks: list[Track], current_index: int = -1,
        *, next_index: int | None = None,
    ) -> None:
        """Синхронизирует снимок модели контроллера, не прерывая текущий звук."""
        self._queue = list(tracks)
        self._queue_index = current_index if -1 <= current_index < len(tracks) else -1
        self._rebuild_shuffle_order()
        if next_index is not None and next_index != self._queue_index:
            if next_index in self._shuffle_order:
                self._shuffle_order.remove(next_index)
                self._shuffle_order.insert(self._shuffle_pos + 1, next_index)
        self.queue_changed.emit(list(self._queue))
        self.queue_index_changed.emit(self._queue_index)

    def play_queue_index(self, index: int) -> bool:
        if not 0 <= index < len(self._queue):
            return False
        previous = self._queue_index
        try:
            track = self.db.get_track(self._queue[index].id)
        except sqlite3.Error as error:
            logger.warning('Не удалось прочитать трек очереди: %s', error)
            self.error_occurred.emit('Не удалось прочитать трек из базы данных.')
            return False
        if track is None:
            self.error_occurred.emit('Трек очереди удалён из библиотеки.')
            return False
        self._queue[index] = track
        self._queue_index = index
        if not self.play_track(track):
            self._queue_index = previous
            return False
        if index in self._shuffle_order:
            self._shuffle_pos = self._shuffle_order.index(index)
        self.queue_index_changed.emit(index)
        return True

    def next_track(self) -> None:
        """Пропускает недоступные файлы, не оставляя ложного текущего индекса."""
        previous = self._queue_index
        previous_shuffle = self._shuffle_pos
        visited: set[int] = set()
        while (index := self._get_next_index()) is not None and index not in visited:
            visited.add(index)
            if self.play_queue_index(index):
                return
            self._queue_index = index
        self._queue_index = previous
        self._shuffle_pos = previous_shuffle
        self.stop()
        self.queue_index_changed.emit(self._queue_index)

    def prev_track(self) -> None:
        if self._player.position() > 3000:
            self.seek(0)
            return
        previous = self._queue_index
        visited: set[int] = set()
        while (index := self._get_prev_index()) is not None and index not in visited:
            visited.add(index)
            if self.play_queue_index(index):
                return
            self._queue_index = index
        self._queue_index = previous

    def seek(self, position_ms: int) -> None:
        self._player.setPosition(position_ms)

    def set_volume(self, volume: int) -> None:
        volume = max(0, min(100, volume))
        self._audio.setVolume(volume / 100.0)
        self.volume_changed.emit(volume)

    def get_volume(self) -> int:
        return round(self._audio.volume() * 100)

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

    def save_playback_state(self) -> None:
        if self._current_track is None or self._changing_source:
            return
        try:
            self.db.save_playback_state(self._current_track.id, self._last_position_ms)
        except sqlite3.Error:
            logger.exception("Не удалось сохранить позицию воспроизведения")

    def shutdown(self) -> None:
        self._save_timer.stop()
        self.stop()

    # ============================================================
    # Внутреннее
    # ============================================================

    def _on_position_changed(self, position_ms: int) -> None:
        # setSource/stop сбрасывают позицию: это не новое место прослушивания.
        if not self._changing_source and self._pending_seek_ms is None:
            self._last_position_ms = max(0, position_ms)
        self.position_changed.emit(self._last_position_ms)

    def _restore_position(self, *_args) -> None:
        if self._changing_source or self._pending_seek_ms is None:
            return
        if not self._player.isSeekable():
            return
        duration = self._player.duration()
        if duration <= 0:
            return
        position_ms = self._pending_seek_ms
        if position_ms >= duration:
            position_ms = 0
        self._pending_seek_ms = None
        self._last_position_ms = position_ms
        self._player.setPosition(position_ms)

    def _resolve_file(self, track: Track) -> Path | None:
        """Возвращает путь к MP3-файлу, если он существует."""
        if not track.file_path:
            return None

        from core.paths import get_data_dir

        path = Path(track.file_path)
        if not path.is_absolute():
            path = get_data_dir() / path
        return path if path.is_file() else None

    def _on_state_changed(self, state) -> None:
        if self._changing_source:
            return
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.state_changed.emit('playing')
        elif state == QMediaPlayer.PlaybackState.PausedState:
            self.save_playback_state()
            self.state_changed.emit('paused')
        else:
            self.state_changed.emit('stopped')

        # Автопереход выполняется только после завершения трека с известной длительностью.
        if state == QMediaPlayer.PlaybackState.StoppedState and self._current_track is not None:
            duration = self._player.duration()
            if duration > 0 and self._player.position() >= duration - 100:
                self._last_position_ms = 0
                self.save_playback_state()
                if self._repeat_mode == 'one':
                    logger.info("Повтор трека")
                    self.play_track(self._current_track, queue=None)
                    return
                if self._autoplay_next:
                    logger.info("Трек закончился, переходим к следующему")
                    self.next_track()
            else:
                self.save_playback_state()

    def _on_error(self, error, error_string: str) -> None:
        if error == QMediaPlayer.Error.NoError:
            return
        msg = _friendly_media_error(error, error_string)
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
            current = self._queue_index
            others = [i for i in indices if i != current]
            random.shuffle(others)
            self._shuffle_order = [current, *others] if current >= 0 else others
            self._shuffle_pos = 0 if current >= 0 else -1
        else:
            self._shuffle_order = indices
            self._shuffle_pos = self._queue_index

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
                    self._shuffle_pos = 1 if len(self._shuffle_order) > 1 else 0
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
            previous = self._shuffle_pos - 1
            if previous < 0:
                if self._repeat_mode != 'all':
                    return None
                previous = len(self._shuffle_order) - 1
            self._shuffle_pos = previous
            return self._shuffle_order[self._shuffle_pos]

        prev_idx = self._queue_index - 1
        if prev_idx < 0:
            if self._repeat_mode == 'all':
                prev_idx = len(self._queue) - 1
            else:
                return None
        return prev_idx