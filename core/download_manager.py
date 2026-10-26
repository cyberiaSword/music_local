"""
Менеджер очереди скачивания.
Работает в отдельном QThread, опрашивает БД и скачивает pending-треки.
"""

import logging
import time
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal, QMutex

from core.database import Database
from core.downloader import download_audio, DownloadResult, is_ytdlp_available
from core.covers import get_cover_for_track
from core.content_filter import ContentFilter


logger = logging.getLogger('yt-local.dlmanager')
MIN_AUDIO_SIZE = 100 * 1024


class DownloadManager(QThread):
    """
    Поток-демон: раз в 2 секунды смотрит на pending-треки и скачивает.

    Сигналы:
        download_started(int, str)  — track_id, title
        download_progress(int, int) — track_id, процент 0..100
        download_finished(int, str) — track_id, путь к файлу
        download_failed(int, str)   — track_id, ошибка
        queue_changed()             — что-то изменилось, обнови UI
    """

    download_started = pyqtSignal(int, str)
    download_progress = pyqtSignal(int, int)
    download_finished = pyqtSignal(int, str)
    download_failed = pyqtSignal(int, str)
    queue_changed = pyqtSignal()

    def __init__(
        self,
        db: Database,
        downloads_dir: Path,
        covers_dir: Path,
        quality_v0: bool = True,
        cover_mode: str = 'auto',
        video_frame_second: int = 15,
        proxy: str | None = None,
        content_filter: ContentFilter | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.db = db
        self.downloads_dir = downloads_dir
        self.covers_dir = covers_dir
        self.quality_v0 = quality_v0
        self.cover_mode = cover_mode
        self.video_frame_second = video_frame_second
        self.proxy = proxy
        self.content_filter = content_filter
        self._stop = False
        self._mutex = QMutex()
        self._attempted_track_ids: set[int] = set()

    def stop(self) -> None:
        """Останавливает поток (мягко)."""
        self._mutex.lock()
        self._stop = True
        self._mutex.unlock()

    def _is_stopped(self) -> bool:
        self._mutex.lock()
        value = self._stop
        self._mutex.unlock()
        return value

    def run(self) -> None:
        """Основной цикл."""
        if not is_ytdlp_available():
            logger.error("yt-dlp не установлен — скачивание невозможно")
            return

        logger.info(f"DownloadManager запущен (папка: {self.downloads_dir})")

        while not self._is_stopped():
            try:
                pending = self.db.get_all(filter_status='pending')
            except Exception as e:
                logger.exception(f"Ошибка чтения pending: {e}")
                self.msleep(3000)
                continue

            if not pending:
                self._attempted_track_ids.clear()
                self.msleep(2000)
                continue

            available = [
                track for track in pending
                if track.id not in self._attempted_track_ids
            ]
            if not available:
                self._attempted_track_ids.clear()
                self.msleep(2000)
                continue

            track = available[0]
            self._attempted_track_ids.add(track.id)
            try:
                self._process_track(track)
            except Exception as error:
                logger.exception(
                    f"Необработанная ошибка трека {track.title} (id={track.id}): {error}"
                )
                try:
                    self.db.set_download_status(track.id, 'failed')
                except Exception:
                    logger.exception(
                        f"Не удалось сохранить статус ошибки трека id={track.id}"
                    )
                self.download_failed.emit(
                    track.id, "Не удалось обработать трек. Проверьте журнал ошибок."
                )
                self.queue_changed.emit()

            if self._is_stopped():
                break

        logger.info("Менеджер загрузок остановлен")

    def _process_track(self, track) -> None:
        """Скачивает один трек и обновляет БД."""
        track_id = track.id
        logger.info(f"Начинаю загрузку: {track.title} (id={track_id})")

        # Помечаем как downloading, чтобы не взять повторно
        self.db.set_download_status(track_id, 'downloading')
        self.download_started.emit(track_id, track.title)
        self.queue_changed.emit()

        last_activity_at = 0.0

        def progress_hook(d: dict) -> None:
            nonlocal last_activity_at
            if d.get('status') == 'downloading':
                now = time.monotonic()
                if now - last_activity_at >= 30:
                    self.db.touch_download_activity(track_id)
                    last_activity_at = now
                total = d.get('total_bytes') or d.get('total_bytes_estimate')
                downloaded = d.get('downloaded_bytes', 0)
                if total and total > 0:
                    pct = int(downloaded * 100 / total)
                    self.download_progress.emit(track_id, pct)
            elif d.get('status') == 'finished':
                self.db.touch_download_activity(track_id)
                self.download_progress.emit(track_id, 100)

        # Скачивание выполняется в этом QThread; сетевой таймаут задаёт yt-dlp.
        result = download_audio(
            url=track.url,
            video_id=track.video_id,
            output_dir=self.downloads_dir,
            quality_v0=self.quality_v0,
            progress_callback=progress_hook,
            proxy=self.proxy,
            content_filter=self.content_filter,
        )

        if self._is_stopped():
            self.db.set_download_status(track_id, 'pending')
            return

        if result.skipped:
            logger.info(f"Отсеян: {track.title} — {result.skip_reason}")
            self.db.set_download_status(track_id, 'skipped')
            self.download_failed.emit(track_id, f"Отсеян: {result.skip_reason}")
            self.queue_changed.emit()
            return

        if not result.success:
            logger.error(f"Ошибка загрузки {track.title}: {result.error}")
            self.db.set_download_status(track_id, 'failed')
            self.download_failed.emit(track_id, result.error)
            self.queue_changed.emit()
            return

        mp3_path = result.mp3_path
        try:
            audio_is_valid = (
                mp3_path is not None
                and mp3_path.is_file()
                and mp3_path.stat().st_size >= MIN_AUDIO_SIZE
            )
        except OSError:
            audio_is_valid = False

        if not audio_is_valid:
            if mp3_path is not None:
                try:
                    if mp3_path.is_file() and mp3_path.stat().st_size < MIN_AUDIO_SIZE:
                        mp3_path.unlink()
                except OSError:
                    logger.warning("Не удалось удалить неполный аудиофайл: %s", mp3_path)
            message = "Загруженный аудиофайл отсутствует или слишком мал. Повторите загрузку."
            self.db.set_download_status(track_id, 'failed', error=message)
            self.download_failed.emit(track_id, message)
            self.queue_changed.emit()
            return

        # ---- Обложка ----
        try:
            cover_path = get_cover_for_track(
                track_id=track_id,
                video_id=track.video_id,
                covers_dir=self.covers_dir,
                mode=self.cover_mode,
                video_frame_second=self.video_frame_second,
            )
        except Exception as error:
            logger.warning(f"Не удалось получить обложку для {track.title}: {error}")
            cover_path = None

        # ---- Обновляем БД ----
        rel_mp3 = self._rel(result.mp3_path)
        self.db.set_download_status(track_id, 'done', file_path=rel_mp3)

        if cover_path:
            self.db.set_cover_path(track_id, str(self._rel(cover_path)))

        logger.info(f"Успешно: {track.title} → {rel_mp3}")
        self.download_finished.emit(track_id, rel_mp3)
        self.queue_changed.emit()

    def _rel(self, path: Path | None) -> str | None:
        """Преобразует абсолютный путь в относительный от data/."""
        if path is None:
            return None
        try:
            base = self.downloads_dir.parent   # data/
            return str(path.relative_to(base))
        except ValueError:
            return str(path)