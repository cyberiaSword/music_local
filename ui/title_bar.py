"""
Кастомный заголовок окна в стиле Spotify.
"""

from PyQt6.QtCore import Qt, QPoint, pyqtSignal
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QLineEdit
)

from ui.icons import get_icon
from ui.styles import COLORS


class TitleBar(QWidget):
    """
    Верхняя полоса окна. Позволяет перетаскивать окно, содержит
    поиск и кнопки управления.

    Сигналы:
        minimize_clicked
        maximize_clicked
        close_clicked
        search_changed = pyqtSignal(str)
    """

    minimize_clicked = pyqtSignal()
    maximize_clicked = pyqtSignal()
    close_clicked = pyqtSignal()
    search_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TitleBar")
        self.setFixedHeight(48)

        # Для перетаскивания окна
        self._drag_pos: QPoint | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(12)

        # Логотип
        from core.version import __version__
        logo = QLabel(f"♪  YT Music Local  v{__version__}")
        logo.setObjectName("TitleBarLogo")
        layout.addWidget(logo)

        # Поиск
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍  Поиск")
        self.search.setFixedWidth(320)
        self.search.textChanged.connect(self.search_changed.emit)
        layout.addWidget(self.search)

        layout.addStretch()

        # Кнопки управления окном
        self.btn_min = self._make_window_button("minimize", "Свернуть")
        self.btn_max = self._make_window_button("maximize", "Развернуть")
        self.btn_close = self._make_window_button("close", "Закрыть", danger=True)

        self.btn_min.clicked.connect(self.minimize_clicked.emit)
        self.btn_max.clicked.connect(self.maximize_clicked.emit)
        self.btn_close.clicked.connect(self.close_clicked.emit)

        layout.addWidget(self.btn_min)
        layout.addWidget(self.btn_max)
        layout.addWidget(self.btn_close)

    def _make_window_button(self, icon_name: str, tooltip: str, danger: bool = False) -> QPushButton:
        btn = QPushButton()
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedSize(36, 32)
        btn.setIcon(get_icon(icon_name, 14, COLORS['text_secondary']))
        btn.setIconSize(btn.iconSize())

        hover_color = "#e81123" if danger else COLORS['bg_tertiary']
        btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
            }}
        """)
        return btn

    # ---------------- Перетаскивание окна ----------------

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_pos and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_pos = None

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """Двойной клик — развернуть/восстановить окно."""
        self.maximize_clicked.emit()