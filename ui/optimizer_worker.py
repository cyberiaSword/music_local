"""
QThread-обёртка для оптимизатора.
"""

import logging
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from core.optimizer import optimize_library, OptimizeResult

logger = logging.getLogger('yt-local.optimizer_worker')


class OptimizerWorker(QThread):
    """Асинхронный оптимизатор."""

    progress = pyqtSignal(int, int, object)   # index, total, OptimizeResult
    finished_ok = pyqtSignal(list)             # list[OptimizeResult]

    def __init__(self, downloads_dir: Path, threshold_kbps: int = 250,
                 dry_run: bool = False, parent=None):
        super().__init__(parent)
        self.downloads_dir = downloads_dir
        self.threshold_kbps = threshold_kbps
        self.dry_run = dry_run
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def _is_stopped(self) -> bool:
        return self._stop

    def run(self) -> None:
        results = optimize_library(
            self.downloads_dir,
            threshold_kbps=self.threshold_kbps,
            dry_run=self.dry_run,
            progress_callback=lambda i, t, r: self.progress.emit(i, t, r),
            stop_flag=self._is_stopped,
        )
        self.finished_ok.emit(results)