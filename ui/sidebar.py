"""
Боковая панель навигации.
"""
from PyQt6.QtCore import pyqtSignal, Qt, QSize
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel, QButtonGroup
)


class Sidebar(QWidget):
    """
    Левая панель с разделами.
    Сигнал section_changed испускается с идентификатором раздела:
        'library' | 'downloads' | 'settings'
    """

    section_changed = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(220)

        from ui.icons import get_icon
        from ui.styles import COLORS

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Логотип
        logo = QLabel("♪  YT Music Local")
        logo.setObjectName("Logo")
        layout.addWidget(logo)

        # Кнопки разделов
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        sections = [
            ("library",   "library",  "Библиотека"),
            ("downloads", "download", "Загрузки"),
            ("settings",  "settings", "Настройки"),
        ]

        for section_id, icon_name, label in sections:
            btn = QPushButton(f"  {label}")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setIcon(get_icon(icon_name, 18, COLORS['text_secondary']))
            btn.setIconSize(QSize(18, 18))
            btn.setProperty('section_id', section_id)
            btn.clicked.connect(lambda _, s=section_id: self._on_click(s))
            self._group.addButton(btn)
            layout.addWidget(btn)

        self._group.buttons()[0].setChecked(True)

        layout.addStretch()

        # Версия внизу
        version = QLabel("  v0.35 · Python + Qt")
        version.setStyleSheet("color: #6a6a6a; font-size: 11px; padding: 12px;")
        layout.addWidget(version)

    def _on_click(self, section: str) -> None:
        self.section_changed.emit(section)
        
    def set_section(self, section_id: str) -> None:
        """Программно выбирает раздел (например, сбросить выделение с 'settings')."""
        for btn in self._group.buttons():
            if btn.property('section_id') == section_id:
                btn.setChecked(True)
                return