"""
Окно настроек.
"""

import logging
from pathlib import Path

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QCheckBox, QSpinBox, QPushButton, QLineEdit, QGroupBox,
    QFormLayout, QProgressBar, QFileDialog, QMessageBox, QTabWidget, QWidget
)

from core.settings import Settings
from ui.optimizer_worker import OptimizerWorker
from ui.styles import COLORS

logger = logging.getLogger('yt-local.ui.settings')


class SettingsDialog(QDialog):
    """Модальное окно настроек."""

    settings_changed = pyqtSignal()

    def __init__(self, settings: Settings, downloads_dir: Path, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.downloads_dir = downloads_dir
        self._optimizer_worker: OptimizerWorker | None = None

        self.setWindowTitle("Настройки")
        self.setMinimumSize(620, 540)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        tabs = QTabWidget()
        tabs.addTab(self._build_general_tab(), "Общие")
        tabs.addTab(self._build_download_tab(), "Скачивание")
        tabs.addTab(self._build_appearance_tab(), "Внешний вид")
        tabs.addTab(self._build_optimizer_tab(), "Оптимизация")
        layout.addWidget(tabs)

        # Кнопки внизу
        buttons = QHBoxLayout()
        buttons.addStretch()

        cancel = QPushButton("Отмена")
        cancel.setObjectName("GhostButton")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)

        save = QPushButton("Сохранить")
        save.setObjectName("PrimaryButton")
        save.clicked.connect(self._save)
        buttons.addWidget(save)

        layout.addLayout(buttons)

    # ============================================================
    # Вкладки
    # ============================================================

    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(16, 16, 16, 16)
        form.setSpacing(12)

        # Папка загрузок
        self.downloads_edit = QLineEdit(str(self.downloads_dir))
        self.downloads_edit.setReadOnly(True)
        browse = QPushButton("...")
        browse.setFixedWidth(40)
        browse.clicked.connect(self._browse_downloads)

        row = QHBoxLayout()
        row.addWidget(self.downloads_edit, stretch=1)
        row.addWidget(browse)
        form.addRow("Папка загрузок:", row)

        # Автозагрузка при старте
        self.auto_download_cb = QCheckBox("Автоматически скачивать новые треки")
        self.auto_download_cb.setChecked(self.settings.get('auto_download', True))
        form.addRow("", self.auto_download_cb)

        # Сворачивать в трей
        self.tray_cb = QCheckBox("Сворачивать в трей при закрытии")
        self.tray_cb.setChecked(self.settings.get('minimize_to_tray', True))
        form.addRow("", self.tray_cb)

        # Запускать свёрнутым
        self.start_minimized_cb = QCheckBox("Запускать приложение свёрнутым в трей")
        self.start_minimized_cb.setChecked(self.settings.get('start_minimized', False))
        form.addRow("", self.start_minimized_cb)

        return page

    def _build_download_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(16, 16, 16, 16)
        form.setSpacing(12)

        # Качество
        self.quality_combo = QComboBox()
        self.quality_combo.addItem("MP3 V0 (~245 kbps) — максимум качества", True)
        self.quality_combo.addItem("MP3 V2 (~190 kbps) — меньше места", False)
        idx = 0 if self.settings.get('audio_quality_v0', True) else 1
        self.quality_combo.setCurrentIndex(idx)
        form.addRow("Качество MP3:", self.quality_combo)

        # Режим обложек
        self.cover_combo = QComboBox()
        self.cover_combo.addItem("Авто (кадр из видео, если есть, иначе постер)", "auto")
        self.cover_combo.addItem("Только постер YouTube", "poster")
        self.cover_combo.addItem("Только кадр из видео", "video_frame")
        cur = self.settings.get('cover_mode', 'auto')
        for i in range(self.cover_combo.count()):
            if self.cover_combo.itemData(i) == cur:
                self.cover_combo.setCurrentIndex(i)
                break
        form.addRow("Обложка:", self.cover_combo)

        # Секунда для кадра
        self.frame_second = QSpinBox()
        self.frame_second.setRange(1, 300)
        self.frame_second.setSuffix(" сек")
        self.frame_second.setValue(self.settings.get('video_frame_second', 15))
        form.addRow("Кадр из видео на:", self.frame_second)

        return page

    def _build_appearance_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(16, 16, 16, 16)
        form.setSpacing(12)

        # Размер списка обложек
        self.cover_size_list = QComboBox()
        self.cover_size_list.addItem("Маленькие (mqdefault 320×180)", "mqdefault")
        self.cover_size_list.addItem("Средние (hqdefault 480×360)", "hqdefault")
        self.cover_size_list.addItem("Большие (maxresdefault 1280×720)", "maxresdefault")
        cur = self.settings.get('cover_size_list', 'hqdefault')
        for i in range(self.cover_size_list.count()):
            if self.cover_size_list.itemData(i) == cur:
                self.cover_size_list.setCurrentIndex(i)
                break
        form.addRow("Размер обложек в списке:", self.cover_size_list)

        # Громкость
        self.volume_spin = QSpinBox()
        self.volume_spin.setRange(0, 100)
        self.volume_spin.setSuffix(" %")
        self.volume_spin.setValue(self.settings.get('player_volume', 70))
        form.addRow("Громкость по умолчанию:", self.volume_spin)

        # Автопереход к следующему треку
        self.autoplay_cb = QCheckBox("Автоматически играть следующий трек")
        self.autoplay_cb.setChecked(self.settings.get('player_autoplay_next', True))
        form.addRow("", self.autoplay_cb)

        return page

    def _build_optimizer_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Описание
        info = QLabel(
            "Файлы с битрейтом выше 250 kbps будут перекодированы в V0 "
            "(~245 kbps VBR). Это освободит место, но снизит качество таких файлов. "
            "Рекомендуется сделать резервную копию папки downloads перед запуском."
        )
        info.setWordWrap(True)
        info.setStyleSheet(
            f"color: {COLORS['text_secondary']};"
            "font-size: 12px;"
            "padding: 8px;"
            f"background-color: {COLORS['bg_tertiary']};"
            "border-radius: 6px;"
        )
        layout.addWidget(info)

        # Порог
        threshold_row = QHBoxLayout()
        threshold_row.addWidget(QLabel("Порог битрейта:"))
        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(128, 320)
        self.threshold_spin.setSuffix(" kbps")
        self.threshold_spin.setValue(self.settings.get('optimize_threshold_kbps', 250))
        threshold_row.addWidget(self.threshold_spin)
        threshold_row.addStretch()
        layout.addLayout(threshold_row)

        # Dry run
        self.dry_run_cb = QCheckBox("Пробный запуск (ничего не удалять)")
        self.dry_run_cb.setChecked(True)
        layout.addWidget(self.dry_run_cb)

        # Кнопки
        buttons_row = QHBoxLayout()
        self.analyze_btn = QPushButton("Анализировать")
        self.analyze_btn.setObjectName("GhostButton")
        self.analyze_btn.clicked.connect(lambda: self._run_optimizer(dry_run=True))
        buttons_row.addWidget(self.analyze_btn)

        self.optimize_btn = QPushButton("Оптимизировать")
        self.optimize_btn.setObjectName("PrimaryButton")
        self.optimize_btn.clicked.connect(lambda: self._run_optimizer(dry_run=False))
        buttons_row.addWidget(self.optimize_btn)

        self.cancel_opt_btn = QPushButton("Стоп")
        self.cancel_opt_btn.setObjectName("GhostButton")
        self.cancel_opt_btn.setEnabled(False)
        self.cancel_opt_btn.clicked.connect(self._cancel_optimizer)
        buttons_row.addWidget(self.cancel_opt_btn)
        buttons_row.addStretch()
        layout.addLayout(buttons_row)

        # Прогресс
        self.opt_progress = QProgressBar()
        self.opt_progress.setVisible(False)
        self.opt_progress.setTextVisible(True)
        layout.addWidget(self.opt_progress)

        self.opt_status = QLabel("")
        self.opt_status.setStyleSheet(f"color: {COLORS['text_secondary']};")
        layout.addWidget(self.opt_status)

        layout.addStretch()
        return page

    # ============================================================
    # Действия
    # ============================================================

    def _browse_downloads(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Выберите папку загрузок")
        if path:
            self.downloads_edit.setText(path)

    def _save(self) -> None:
        """Сохраняет все настройки."""
        s = self.settings
        s.set('auto_download', self.auto_download_cb.isChecked())
        s.set('minimize_to_tray', self.tray_cb.isChecked())
        s.set('start_minimized', self.start_minimized_cb.isChecked())
        s.set('audio_quality_v0', self.quality_combo.currentData())
        s.set('cover_mode', self.cover_combo.currentData())
        s.set('video_frame_second', self.frame_second.value())
        s.set('cover_size_list', self.cover_size_list.currentData())
        s.set('player_volume', self.volume_spin.value())
        s.set('player_autoplay_next', self.autoplay_cb.isChecked())
        s.set('optimize_threshold_kbps', self.threshold_spin.value())
        s.save()
        self.settings_changed.emit()
        self.accept()

    # ============================================================
    # Оптимизатор
    # ============================================================

    def _run_optimizer(self, dry_run: bool) -> None:
        if self._optimizer_worker and self._optimizer_worker.isRunning():
            return

        if not dry_run:
            reply = QMessageBox.question(
                self, "Подтверждение",
                "Перекодирование изменит файлы в папке downloads. "
                "Продолжить?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self.opt_progress.setVisible(True)
        self.opt_progress.setRange(0, 100)
        self.opt_progress.setValue(0)
        self.opt_status.setText("Подготовка...")
        self.analyze_btn.setEnabled(False)
        self.optimize_btn.setEnabled(False)
        self.cancel_opt_btn.setEnabled(True)

        self._optimizer_worker = OptimizerWorker(
            self.downloads_dir,
            threshold_kbps=self.threshold_spin.value(),
            dry_run=dry_run,
        )
        self._optimizer_worker.progress.connect(self._on_opt_progress)
        self._optimizer_worker.finished_ok.connect(self._on_opt_finished)
        self._optimizer_worker.start()

    def _cancel_optimizer(self) -> None:
        if self._optimizer_worker:
            self._optimizer_worker.stop()
            self.opt_status.setText("Остановка...")

    def _on_opt_progress(self, index: int, total: int, result) -> None:
        pct = int(index * 100 / total) if total > 0 else 0
        self.opt_progress.setValue(pct)
        self.opt_status.setText(
            f"{index}/{total}  ·  {result.path.name}  ·  {result.action}"
        )

    def _on_opt_finished(self, results: list) -> None:
        self.analyze_btn.setEnabled(True)
        self.optimize_btn.setEnabled(True)
        self.cancel_opt_btn.setEnabled(False)

        optimized = sum(1 for r in results if r.action == 'optimized')
        skipped = sum(1 for r in results if r.action == 'skipped')
        failed = sum(1 for r in results if r.action == 'failed')
        saved = sum(r.old_size - r.new_size for r in results if r.action == 'optimized')

        self.opt_status.setText(
            f"Готово. Сжато: {optimized}, пропущено: {skipped}, ошибок: {failed}. "
            f"Освобождено: {saved / 1024 / 1024:.1f} МБ"
        )
        self.opt_progress.setValue(100)
        self._optimizer_worker = None

    def closeEvent(self, event) -> None:
        self._cancel_optimizer()
        super().closeEvent(event)