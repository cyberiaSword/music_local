"""
Менеджер очереди скачивания.
Работает в отдельном QThread, опрашивает БД и скачивает pending-треки.
"""

import logging
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal, QMutex

from core.database import Database
from core.downloader import download_audio, DownloadResult, is_ytdlp_available
from core.covers import get_cover_for_track
import concurrent.futures

logger = logging.getLogger('yt-local.dlmanager')


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

        self._stop = False
        self._mutex = QMutex()

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
                self.msleep(2000)
                continue

            # Берём первый попавшийся
            track = pending[0]
            self._process_track(track)

            if self._is_stopped():
                break

        logger.info("DownloadManager остановлен")

    def _process_track(self, track) -> None:
        """Скачивает один трек и обновляет БД."""
        track_id = track.id
        logger.info(f"Начинаю загрузку: {track.title} (id={track_id})")

        # Помечаем как downloading, чтобы не взять повторно
        self.db.set_download_status(track_id, 'downloading')
        self.download_started.emit(track_id, track.title)
        self.queue_changed.emit()

        # Колбэк прогресса yt-dlp
        def progress_hook(d: dict) -> None:
            if d.get('status') == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate')
                downloaded = d.get('downloaded_bytes', 0)
                if total and total > 0:
                    pct = int(downloaded * 100 / total)
                    self.download_progress.emit(track_id, pct)
            elif d.get('status') == 'finished':
                self.download_progress.emit(track_id, 100)

        # Скачиваем
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
            download_audio,
            url=track.url,
            video_id=track.video_id,
            output_dir=self.downloads_dir,
            quality_v0=self.quality_v0,
            progress_callback=progress_hook,
            proxy=self.proxy,
        )
        try:
            result = future.result(timeout=300)   # 5 минут на скачивание
        except concurrent.futures.TimeoutError:
            logger.error(f"Таймаут скачивания: {track.title}")
            self.db.set_download_status(track.id, 'failed')
            self.download_failed.emit(track.id, "Таймаут (5 минут)")
            return


        if self._is_stopped():
            self.db.set_download_status(track_id, 'pending')
            return

        if not result.success:
            logger.error(f"Ошибка загрузки {track.title}: {result.error}")
            self.db.set_download_status(track_id, 'failed')
            self.download_failed.emit(track_id, result.error)
            self.queue_changed.emit()
            return

        # ---- Обложка ----
        cover_path = get_cover_for_track(
            track_id=track_id,
            video_id=track.video_id,
            covers_dir=self.covers_dir,
            mode=self.cover_mode,
            video_frame_second=self.video_frame_second,
        )

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