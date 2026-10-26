"""
Окно настроек.
"""

import logging
import subprocess
from pathlib import Path

from PyQt6.QtCore import QSignalBlocker, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox,
    QCheckBox, QSpinBox, QPushButton, QLineEdit, QFormLayout,
    QProgressBar, QFileDialog, QMessageBox, QTabWidget, QWidget,
    QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem,
)

from core.settings import Settings
from core.paths import get_data_dir
from core.cookies_updater import update_cookies_from_browser, check_cookies_valid
from ui.optimizer_worker import OptimizerWorker
from ui.styles import COLORS

logger = logging.getLogger('yt-local.ui.settings')


class SettingsDialog(QDialog):
    """Модальное окно настроек."""

    settings_changed = pyqtSignal()
    global_hotkeys_toggled = pyqtSignal(bool)

    def __init__(self, settings: Settings, downloads_dir: Path, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.downloads_dir = downloads_dir
        self._optimizer_worker: OptimizerWorker | None = None

        self.setWindowTitle("Настройки")
        self.setMinimumSize(650, 600)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        tabs = QTabWidget()
        tabs.addTab(self._build_general_tab(), "Общие")
        tabs.addTab(self._build_download_tab(), "Скачивание")
        tabs.addTab(self._build_filter_tab(), "Фильтры")
        tabs.addTab(self._build_appearance_tab(), "Внешний вид")
        tabs.addTab(self._build_hotkeys_tab(), "Горячие клавиши")
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

    def set_global_hotkeys_enabled(self, enabled: bool) -> None:
        """Обновляет желаемое состояние без повторного запроса к MainWindow."""
        with QSignalBlocker(self.global_hotkeys_cb):
            self.global_hotkeys_cb.setChecked(enabled)

    # ============================================================
    # Вкладки
    # ============================================================

    def _build_hotkeys_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.global_hotkeys_cb = QCheckBox("Включить глобальные клавиши")
        self.global_hotkeys_cb.setChecked(
            self.settings.get('global_hotkeys_enabled', True)
        )
        self.global_hotkeys_cb.toggled.connect(self.global_hotkeys_toggled.emit)
        layout.addWidget(self.global_hotkeys_cb)

        hint = QLabel(
            "Применяется сразу. Кнопка «Отмена» не откатывает эту настройку. "
            "Локальные сочетания работают только в окне приложения."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        from ui.shortcuts import BINDINGS

        global_bindings = (
            ('Media Play/Pause', 'Играть / Пауза'),
            ('Media Next', 'Следующий трек'),
            ('Media Previous', 'Предыдущий трек'),
            ('Media Stop', 'Остановить воспроизведение'),
            ('Ctrl+Alt+Space', 'Играть / Пауза'),
        )
        rows = [('Глобальные', sequence, label)
                for sequence, label in global_bindings]
        rows.extend(('В окне', sequence, label)
                    for _action_id, sequence, label in BINDINGS)
        self.hotkeys_table = QTableWidget(len(rows), 3)
        self.hotkeys_table.setHorizontalHeaderLabels(
            ['Область', 'Сочетание', 'Действие']
        )
        self.hotkeys_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.hotkeys_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.hotkeys_table.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
        self.hotkeys_table.verticalHeader().hide()
        self.hotkeys_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self.hotkeys_table.horizontalHeader().setStretchLastSection(True)
        for row_index, row in enumerate(rows):
            for column, text in enumerate(row):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.hotkeys_table.setItem(row_index, column, item)
        layout.addWidget(self.hotkeys_table)
        return page

    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(16, 16, 16, 16)
        form.setSpacing(12)

        self.downloads_edit = QLineEdit(str(self.downloads_dir))
        self.downloads_edit.setReadOnly(True)
        browse = QPushButton("...")
        browse.setFixedWidth(40)
        browse.clicked.connect(self._browse_downloads)

        row = QHBoxLayout()
        row.addWidget(self.downloads_edit, stretch=1)
        row.addWidget(browse)
        form.addRow("Папка загрузок:", row)

        self.auto_download_cb = QCheckBox("Автоматически скачивать новые треки")
        self.auto_download_cb.setChecked(self.settings.get('auto_download', True))
        form.addRow("", self.auto_download_cb)

        self.tray_cb = QCheckBox("Сворачивать в трей при закрытии")
        self.tray_cb.setChecked(self.settings.get('minimize_to_tray', True))
        form.addRow("", self.tray_cb)

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

        # ---- Обновление данных авторизации ----
        cookies_label = QLabel("Данные авторизации YouTube")
        cookies_label.setStyleSheet(
            "font-weight: 600;"
            f"color: {COLORS['text_primary']};"
            "padding-top: 12px;"
        )
        form.addRow(cookies_label)

        cookies_desc = QLabel(
            "Файлы cookie из браузера используются при загрузке. "
            "Если YouTube их отклонит, приложение повторит попытку без них."
        )
        cookies_desc.setWordWrap(True)
        cookies_desc.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 11px;")
        form.addRow(cookies_desc)

        self.cookies_status = QLabel("Проверка...")
        self.cookies_status.setWordWrap(True)
        self.cookies_status.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 12px; padding: 4px;"
        )
        form.addRow("Статус:", self.cookies_status)

        cookies_row = QHBoxLayout()
        self.update_cookies_btn = QPushButton("Обновить cookies из браузера")
        self.update_cookies_btn.setObjectName("GhostButton")
        self.update_cookies_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_cookies_btn.clicked.connect(self._on_update_cookies)
        cookies_row.addWidget(self.update_cookies_btn)

        self.open_cookies_folder_btn = QPushButton("Открыть папку")
        self.open_cookies_folder_btn.setObjectName("GhostButton")
        self.open_cookies_folder_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_cookies_folder_btn.clicked.connect(self._open_cookies_folder)
        cookies_row.addWidget(self.open_cookies_folder_btn)
        cookies_row.addStretch()
        form.addRow("", cookies_row)

        self._refresh_cookies_status()
        return page

    def _build_filter_tab(self) -> QWidget:
        """Вкладка «Фильтры» — правила скачивания."""
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(16, 16, 16, 16)
        form.setSpacing(12)

        # Описание
        info = QLabel(
            "Эти настройки определяют, какие видео скачивать, а какие — пропускать. "
            "Отсеянные треки помечаются как «Пропущено» и не занимают место на диске."
        )
        info.setWordWrap(True)
        info.setStyleSheet(
            f"color: {COLORS['text_secondary']};"
            "font-size: 12px;"
            "padding: 8px;"
            f"background-color: {COLORS['bg_tertiary']};"
            "border-radius: 6px;"
        )
        form.addRow(info)

        # Максимальная длительность
        self.max_duration_spin = QSpinBox()
        self.max_duration_spin.setRange(0, 36000)  # до 10 часов
        self.max_duration_spin.setSuffix(" сек")
        self.max_duration_spin.setSpecialValueText("Без ограничений")
        self.max_duration_spin.setValue(self.settings.get('max_duration_seconds', 600))
        form.addRow("Максимальная длительность:", self.max_duration_spin)

        hint1 = QLabel("0 = без ограничений. По умолчанию: 600 сек (10 мин)")
        hint1.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 11px;")
        form.addRow("", hint1)

        # Исключать подкасты
        self.exclude_podcasts_cb = QCheckBox("Исключать подкасты")
        self.exclude_podcasts_cb.setChecked(self.settings.get('exclude_podcasts', True))
        form.addRow("", self.exclude_podcasts_cb)

        # Исключать стримы
        self.exclude_livestreams_cb = QCheckBox("Исключать стримы и трансляции")
        self.exclude_livestreams_cb.setChecked(self.settings.get('exclude_livestreams', True))
        form.addRow("", self.exclude_livestreams_cb)

        # Дополнительные ключевые слова
        self.extra_keywords_edit = QLineEdit()
        self.extra_keywords_edit.setPlaceholderText("через запятую: dj set, megamix, ...")
        extra_kw = self.settings.get('extra_exclude_keywords', [])
        self.extra_keywords_edit.setText(', '.join(extra_kw))
        form.addRow("Доп. ключевые слова:", self.extra_keywords_edit)

        hint2 = QLabel(
            "Видео, в названии которых встречаются эти слова, будут пропущены. "
            "Разделяйте запятыми."
        )
        hint2.setWordWrap(True)
        hint2.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 11px;")
        form.addRow("", hint2)

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

        threshold_row = QHBoxLayout()
        threshold_row.addWidget(QLabel("Порог битрейта:"))
        self.threshold_spin = QSpinBox()
        self.threshold_spin.setRange(128, 320)
        self.threshold_spin.setSuffix(" kbps")
        self.threshold_spin.setValue(self.settings.get('optimize_threshold_kbps', 250))
        threshold_row.addWidget(self.threshold_spin)
        threshold_row.addStretch()
        layout.addLayout(threshold_row)

        self.dry_run_cb = QCheckBox("Пробный запуск (ничего не удалять)")
        self.dry_run_cb.setChecked(True)
        layout.addWidget(self.dry_run_cb)

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
    # Cookies
    # ============================================================

    def _refresh_cookies_status(self) -> None:
        """Обновляет статус cookies."""
        cookies_path = get_data_dir() / 'cookies.txt'
        is_valid, reason = check_cookies_valid(cookies_path)

        if is_valid:
            self.cookies_status.setText(f"Проверка пройдена: {reason}")
            self.cookies_status.setStyleSheet(
                f"color: {COLORS['accent_green']}; font-size: 12px; padding: 4px;"
            )
        else:
            self.cookies_status.setText(f"Проверка не пройдена: {reason}")
            self.cookies_status.setStyleSheet(
                f"color: {COLORS['accent_red']}; font-size: 12px; padding: 4px;"
            )

    def _on_update_cookies(self) -> None:
        """Обновляет данные авторизации и показывает результат рядом с кнопкой."""
        self.update_cookies_btn.setEnabled(False)
        self.update_cookies_btn.setText("Читаю данные авторизации...")

        try:
            cookies_path = get_data_dir() / 'cookies.txt'
            result = update_cookies_from_browser(cookies_path)
            if result.success:
                is_valid, reason = check_cookies_valid(cookies_path)
                if is_valid:
                    self.cookies_status.setText(
                        f"Проверка пройдена: получено файлов cookie — "
                        f"{result.cookies_count} из браузера {result.browser}. "
                        "Данные будут использованы при следующей загрузке."
                    )
                    self.cookies_status.setStyleSheet(
                        f"color: {COLORS['accent_green']}; font-size: 12px; padding: 4px;"
                    )
                else:
                    self.cookies_status.setText(f"Проверка не пройдена: {reason}")
                    self.cookies_status.setStyleSheet(
                        f"color: {COLORS['accent_red']}; font-size: 12px; padding: 4px;"
                    )
            else:
                self.cookies_status.setText(
                    "Не удалось обновить данные авторизации. Проверьте настройки браузера."
                )
                self.cookies_status.setStyleSheet(
                    f"color: {COLORS['accent_red']}; font-size: 12px; padding: 4px;"
                )
        finally:
            self.update_cookies_btn.setEnabled(True)
            self.update_cookies_btn.setText("Обновить данные авторизации из браузера")

    def _open_cookies_folder(self) -> None:
        """Открывает папку data/ в проводнике."""
        data_dir = get_data_dir()
        try:
            subprocess.Popen(['explorer', str(data_dir)])
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось открыть папку: {e}")

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
        s.set('global_hotkeys_enabled', self.global_hotkeys_cb.isChecked())
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

        # Фильтры
        s.set('max_duration_seconds', self.max_duration_spin.value())
        s.set('exclude_podcasts', self.exclude_podcasts_cb.isChecked())
        s.set('exclude_livestreams', self.exclude_livestreams_cb.isChecked())
        kw_text = self.extra_keywords_edit.text().strip()
        extra_kw = [kw.strip() for kw in kw_text.split(',') if kw.strip()]
        s.set('extra_exclude_keywords', extra_kw)

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