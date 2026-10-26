"""Контроллер очереди загрузок и обновления её представления."""

from PyQt6.QtCore import QObject, pyqtSignal


class DownloadController(QObject):
    toast_requested = pyqtSignal(str)

    def __init__(
        self,
        manager,
        track_controller,
        downloads_page,
        status_bar,
        refresh_stats,
        parent=None,
    ):
        super().__init__(parent)
        self.manager = manager
        self.track_controller = track_controller
        self.downloads_page = downloads_page
        self.status_bar = status_bar
        self.refresh_stats = refresh_stats

        manager.download_started.connect(self._on_started)
        manager.download_progress.connect(self._on_progress)
        manager.download_finished.connect(self._on_finished)
        manager.download_failed.connect(self._on_failed)
        manager.queue_changed.connect(self.refresh_stats)

    def _on_started(self, track_id: int, title: str) -> None:
        self.status_bar.showMessage(f"Началась загрузка: {title}", 8000)
        self.track_controller.refresh_track(track_id)
        self.downloads_page.refresh()

    def _on_progress(self, track_id: int, percent: int) -> None:
        self.track_controller.set_progress(track_id, percent)
        self.downloads_page.update_progress(track_id, percent)

    def _on_finished(self, track_id: int, path: str) -> None:
        self.track_controller.clear_progress(track_id)
        self.track_controller.refresh_track(track_id)
        self.downloads_page.refresh()
        self.status_bar.showMessage("Загрузка завершена", 6000)
        self.toast_requested.emit("Трек успешно скачан")
        self.refresh_stats()

    def _on_failed(self, track_id: int, error: str) -> None:
        self.track_controller.clear_progress(track_id)
        self.track_controller.refresh_track(track_id)
        self.downloads_page.refresh()
        message = error.strip() or "Не удалось скачать трек. Повторите попытку позже."
        self.status_bar.showMessage(message[:220], 10000)
        self.toast_requested.emit(message)
        self.refresh_stats()
