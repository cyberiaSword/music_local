"""
Страница «Загрузки» — очередь и история скачивания.
"""

import logging

from PyQt6.QtCore import QPoint, Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QPushButton, QAbstractItemView, QMenu, QStackedWidget
)

from core.database import Database, Playlist, Track
from ui.feedback_widgets import EmptyStateWidget, SkeletonPlaceholder
from ui.status_icons import get_status_icon, get_status_label
from ui.styles import COLORS

logger = logging.getLogger('yt-local.ui.downloads')


class DownloadsLoader(QThread):
    loaded = pyqtSignal(int, int, object, str)

    def __init__(self, db: Database, request_id: int, offset: int, parent=None):
        super().__init__(parent)
        self.db = db
        self.request_id = request_id
        self.offset = offset

    def run(self) -> None:
        if self.isInterruptionRequested():
            return
        try:
            tracks = self.db.get_downloads_page(limit=100, offset=self.offset)
            if not self.isInterruptionRequested():
                self.loaded.emit(self.request_id, self.offset, tracks, "")
        except Exception as error:
            logger.exception("Ошибка фоновой загрузки страницы загрузок")
            if not self.isInterruptionRequested():
                self.loaded.emit(self.request_id, self.offset, [], str(error))


class DownloadsPage(QWidget):
    """Показывает треки со статусами pending / downloading / done / failed."""

    refresh_requested = pyqtSignal()
    enqueue_requested = pyqtSignal(int, str)
    playlist_add_requested = pyqtSignal(str, int)

    def set_playlists(self, playlists: list[Playlist]) -> None:
        self._playlists = list(playlists)

    def _show_context_menu(self, position: QPoint) -> None:
        index = self.table.indexAt(position)
        if not index.isValid():
            return
        item = self.table.item(index.row(), 0)
        track_id = item.data(Qt.ItemDataRole.UserRole) if item is not None else None
        if not isinstance(track_id, int):
            return
        self.table.setCurrentCell(index.row(), index.column())
        menu = QMenu(self)
        next_action = menu.addAction("Играть следующим")
        next_action.triggered.connect(
            lambda: self.enqueue_requested.emit(track_id, "next"))
        end_action = menu.addAction("Добавить в очередь")
        end_action.triggered.connect(
            lambda: self.enqueue_requested.emit(track_id, "end"))
        submenu = menu.addMenu("Добавить в плейлист")
        submenu.setEnabled(bool(self._playlists))
        for playlist in self._playlists:
            action = submenu.addAction(playlist.name)
            action.triggered.connect(
                lambda checked=False, target=playlist.id:
                self.playlist_add_requested.emit(target, track_id))
        menu.exec(self.table.viewport().mapToGlobal(position))
        menu.deleteLater()

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._playlists: list[Playlist] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(12)

        # ---- Заголовок ----
        top = QHBoxLayout()
        title = QLabel("Загрузки")
        title.setObjectName("SectionTitle")
        top.addWidget(title)
        top.addStretch()

        self.refresh_btn = QPushButton("  Обновить")
        self.refresh_btn.setObjectName("GhostButton")
        self.refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        top.addWidget(self.refresh_btn)

        layout.addLayout(top)

        # ---- Таблица ----
        self.table = QTableWidget()
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(
            ["Название", "Исполнитель", "Статус", "Прогресс", "Проигрываний"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setShowGrid(False)
        self.table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {COLORS['bg_secondary']};
                border: none;
                border-radius: 8px;
                gridline-color: transparent;
                color: {COLORS['text_primary']};
            }}
            QTableWidget::item {{
                padding: 8px;
                border-bottom: 1px solid {COLORS['border']};
            }}
            QTableWidget::item:selected {{
                background-color: {COLORS['bg_elevated']};
            }}
            QHeaderView::section {{
                background-color: {COLORS['bg_tertiary']};
                color: {COLORS['text_secondary']};
                border: none;
                padding: 10px 8px;
                font-weight: 600;
            }}
        """)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)

        self.content_stack = QStackedWidget()
        self.content_stack.addWidget(self.table)
        self.empty_state = EmptyStateWidget()
        self.empty_state.set_state(
            "download", "Загрузок пока нет",
            "Добавьте трек в библиотеку и запустите его загрузку.", "Обновить"
        )
        self.empty_state.action_requested.connect(self.refresh)
        self.content_stack.addWidget(self.empty_state)
        self.skeleton = SkeletonPlaceholder(rows=5, parent=self)
        self.content_stack.addWidget(self.skeleton)
        layout.addWidget(self.content_stack, stretch=1)

        self._request_id = 0
        self._offset = 0
        self._has_more = True
        self._page_loading = False
        self._workers: set[DownloadsLoader] = set()
        self.refresh_btn.clicked.connect(self.refresh)
        self.table.verticalScrollBar().valueChanged.connect(self._maybe_load_more)
        self._reload()

    # ============================================================
    # Перезагрузка
    # ============================================================

    def refresh(self) -> None:
        self._reload()

    def _reload(self) -> None:
        self._request_id += 1
        self._offset = 0
        self._has_more = True
        self._page_loading = False
        self.table.clearContents()
        self.table.setRowCount(0)
        self.content_stack.setCurrentWidget(self.skeleton)
        self.skeleton.start()
        self._start_page(0)

    def _start_page(self, offset: int) -> None:
        self._page_loading = True
        worker = DownloadsLoader(self.db, self._request_id, offset, self)
        self._workers.add(worker)
        worker.loaded.connect(self._on_loaded)
        worker.finished.connect(lambda current=worker: self._workers.discard(current))
        worker.start()

    def _on_loaded(
        self, request_id: int, offset: int, tracks: list[Track], error: str
    ) -> None:
        if request_id != self._request_id:
            return
        self._page_loading = False
        if error:
            self._has_more = False
            if offset == 0:
                self.skeleton.stop()
                self.empty_state.set_state(
                    "x-circle", "Не удалось загрузить список загрузок",
                    "Проверьте подключение к базе данных и повторите попытку.", "Повторить"
                )
                self.content_stack.setCurrentWidget(self.empty_state)
            else:
                logger.warning("Не удалось загрузить следующую страницу загрузок")
            return
        self._has_more = len(tracks) == 100
        self._offset = offset + len(tracks)
        if not tracks and offset == 0:
            self.skeleton.stop()
            self.empty_state.set_state(
                "download", "Загрузок пока нет",
                "Добавьте трек в библиотеку и запустите его загрузку.", "Обновить"
            )
            self.content_stack.setCurrentWidget(self.empty_state)
            return
        self._render_tracks(tracks, offset)
        self.skeleton.stop()
        self.content_stack.setCurrentWidget(self.table)

    def _maybe_load_more(self, value: int) -> None:
        scrollbar = self.table.verticalScrollBar()
        if (
            not self._page_loading
            and self._has_more
            and scrollbar.maximum() > 0
            and value >= scrollbar.maximum() - 120
        ):
            self._start_page(self._offset)

    def _render_tracks(self, tracks: list[Track], start_row: int) -> None:
        self.table.setRowCount(start_row + len(tracks))

        for row, t in enumerate(tracks, start=start_row):
            # Название (сохраняем track_id в UserRole)
            title_item = QTableWidgetItem(t.title)
            title_item.setData(Qt.ItemDataRole.UserRole, t.id)
            self.table.setItem(row, 0, title_item)

            # Исполнитель
            self.table.setItem(row, 1, QTableWidgetItem(t.channel or '—'))

            # Статус: иконка + текст
            status_item = QTableWidgetItem(get_status_label(t.download_status))
            status_item.setIcon(get_status_icon(t.download_status, 16))
            self.table.setItem(row, 2, status_item)

            # Прогресс
            if t.download_status == 'downloading':
                bar = QProgressBar()
                bar.setRange(0, 100)
                bar.setValue(0)
                bar.setTextVisible(False)
                bar.setFixedHeight(6)
                bar.setStyleSheet(f"""
                    QProgressBar {{
                        background-color: {COLORS['bg_tertiary']};
                        border: none;
                        border-radius: 3px;
                    }}
                    QProgressBar::chunk {{
                        background-color: {COLORS['accent_green']};
                        border-radius: 3px;
                    }}
                """)
                self.table.setCellWidget(row, 3, bar)
            elif t.download_status == 'done':
                self.table.setItem(row, 3, QTableWidgetItem("100%"))
            else:
                self.table.setItem(row, 3, QTableWidgetItem("—"))

            # Проигрываний
            self.table.setItem(row, 4, QTableWidgetItem(str(t.play_count)))


    def update_progress(self, track_id: int, percent: int) -> None:
        """Обновляет прогресс-бар одной строки."""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            if item.data(Qt.ItemDataRole.UserRole) == track_id:
                widget = self.table.cellWidget(row, 3)
                if isinstance(widget, QProgressBar):
                    widget.setValue(percent)
                return
        # Если строки нет — трек ещё не отображён, перезагрузим
        self._reload()

    def shutdown(self) -> None:
        self._request_id += 1
        self.skeleton.stop()
        for worker in tuple(self._workers):
            worker.requestInterruption()
            worker.wait()
        self._workers.clear()