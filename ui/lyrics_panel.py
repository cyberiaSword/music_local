"""
Панель с текстом песни.
"""

import logging

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont, QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QPushButton, QSizePolicy
)

from core.lyrics import LyricsData, find_current_line
from ui.styles import COLORS

logger = logging.getLogger('yt-local.ui.lyrics')


class LyricsPanel(QWidget):
    """
    Боковая панель с текстом.
    Скрывается/показывается кнопкой в плеере.
    """

    closed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LyricsPanel")
        self.setFixedWidth(360)

        self._lines: list = []
        self._line_widgets: list[QLabel] = []
        self._active_index: int = -1

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- Заголовок ----
        header = QWidget()
        header.setFixedHeight(48)
        header.setStyleSheet(f"background-color: {COLORS['bg_secondary']};")
        h_layout = QHBoxLayout(header)
        h_layout.setContentsMargins(16, 0, 8, 0)

        title = QLabel("Текст песни")
        title.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            "font-size: 13px; font-weight: 600;"
        )
        h_layout.addWidget(title)
        h_layout.addStretch()

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {COLORS['text_secondary']};
                border: none;
                border-radius: 14px;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['bg_elevated']};
                color: {COLORS['text_primary']};
            }}
        """)
        close_btn.clicked.connect(self._on_close)
        h_layout.addWidget(close_btn)

        root.addWidget(header)

        # ---- Прокрутка ----
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll.setStyleSheet(f"""
            QScrollArea {{
                background-color: {COLORS['bg_secondary']};
                border: none;
            }}
            QScrollArea > QWidget > QWidget {{
                background-color: {COLORS['bg_secondary']};
            }}
        """)

        self.content = QWidget()
        self.content.setStyleSheet(f"background-color: {COLORS['bg_secondary']};")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(24, 32, 24, 200)
        self.content_layout.setSpacing(14)

        # Заглушка по умолчанию
        self.placeholder = QLabel("Текст не загружен")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setStyleSheet(
            f"color: {COLORS['text_muted']};"
            "font-size: 14px;"
            "padding: 60px 20px;"
        )
        self.content_layout.addWidget(self.placeholder)
        self.content_layout.addStretch()

        self.scroll.setWidget(self.content)
        root.addWidget(self.scroll, stretch=1)

    # ============================================================
    # Публичный API
    # ============================================================

    def show_lyrics(self, data: LyricsData | None, title: str = '') -> None:
        """Отображает текст. Если None — заглушка."""
        self._clear()

        if data is None or data.is_empty():
            self.placeholder.setText(
                "Текст не найден\n\n"
                "Попробуйте открыть поиск в браузере"
            )
            self.placeholder.show()
            return

        self.placeholder.hide()
        self._lines = data.lines

        # Если текст НЕ синхронизированный — показываем как обычный
        font_size = 15
        for line in data.lines:
            label = QLabel(line.text)
            label.setWordWrap(True)
            label.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
            )
            font = QFont()
            font.setPointSize(font_size)
            font.setBold(False)
            label.setFont(font)
            label.setStyleSheet(
                f"color: {COLORS['text_secondary']};"
                "padding: 2px 0;"
                "background: transparent;"
            )
            self._line_widgets.append(label)
            self.content_layout.insertWidget(
                self.content_layout.count() - 1, label
            )

        self._active_index = -1

    def update_position(self, position_ms: int, is_synced: bool) -> None:
        """Обновляет активную строку по текущей позиции."""
        if not is_synced or not self._lines:
            return

        new_index = find_current_line(self._lines, position_ms)
        if new_index == self._active_index:
            return

        # Сбросить старую
        if 0 <= self._active_index < len(self._line_widgets):
            self._style_line(self._active_index, active=False)

        self._active_index = new_index

        # Подсветить новую
        if 0 <= new_index < len(self._line_widgets):
            self._style_line(new_index, active=True)
            self._scroll_to(new_index)

    # ============================================================
    # Внутреннее
    # ============================================================

    def _style_line(self, index: int, active: bool) -> None:
        label = self._line_widgets[index]
        font = label.font()
        if active:
            font.setBold(True)
            label.setStyleSheet(
                f"color: {COLORS['accent_green']};"
                "padding: 2px 0;"
                "background: transparent;"
            )
        else:
            font.setBold(False)
            label.setStyleSheet(
                f"color: {COLORS['text_secondary']};"
                "padding: 2px 0;"
                "background: transparent;"
            )
        label.setFont(font)

    def _scroll_to(self, index: int) -> None:
        """Плавно прокручивает так, чтобы активная строка была по центру."""
        label = self._line_widgets[index]
        scrollbar = self.scroll.verticalScrollBar()

        # Позиция центра виджета относительно содержимого
        y = label.y()
        h = label.height()
        viewport_h = self.scroll.viewport().height()

        target = y - (viewport_h // 2) + (h // 2)
        target = max(0, min(target, scrollbar.maximum()))

        from PyQt6.QtCore import QPropertyAnimation, QEasingCurve
        anim = QPropertyAnimation(scrollbar, b"value", self)
        anim.setDuration(300)
        anim.setStartValue(scrollbar.value())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

    def _clear(self) -> None:
        """Удаляет все строки из layout."""
        for w in self._line_widgets:
            w.deleteLater()
        self._line_widgets.clear()
        self._lines = []
        self._active_index = -1
        self.placeholder.show()

    def _on_close(self) -> None:
        self.closed.emit()