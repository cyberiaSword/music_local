"""
Страница «Загрузки» — очередь и история скачивания.
"""

import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QProgressBar,
    QPushButton, QAbstractItemView
)

from core.database import Database
from ui.status_icons import get_status_icon, get_status_label
from ui.styles import COLORS

logger = logging.getLogger('yt-local.ui.downloads')


class DownloadsPage(QWidget):
    """Показывает треки со статусами pending / downloading / done / failed."""

    refresh_requested = pyqtSignal()

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db

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
        self.refresh_btn.clicked.connect(self._reload)
        top.addWidget(self.refresh_btn)

        layout.addLayout(top)

        # ---- Таблица ----
        self.table = QTableWidget()
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

        layout.addWidget(self.table, stretch=1)

        self._reload()

    # ============================================================
    # Перезагрузка
    # ============================================================

    def _reload(self) -> None:
        """Перечитывает все треки из БД."""
        try:
            tracks = self.db.get_all(sort_by='last_played', sort_desc=True)
        except Exception as e:
            logger.exception(f"Ошибка загрузки загрузок: {e}")
            return

        # Сортируем: downloading, pending, failed, done
        order = {'downloading': 0, 'pending': 1, 'failed': 2, 'done': 3}
        tracks.sort(key=lambda t: (order.get(t.download_status, 4), t.id))

        self.table.setRowCount(len(tracks))

        for row, t in enumerate(tracks):
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
        """
        Обновляет прогресс-бар для downloading-трека.
        Для простоты перезагружает всю таблицу — на 100+ треках не критично.
        """
        self._reload()

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