"""
Иконка в системном трее.
"""

import logging

from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QApplication

from ui.styles import COLORS

logger = logging.getLogger('yt-local.ui.tray')


class Tray(QSystemTrayIcon):
    """
    Системный трей.
    Сигналы:
        show_window_requested
        play_pause_requested
        next_requested
        prev_requested
        quit_requested
    """

    show_window_requested = pyqtSignal()
    play_pause_requested = pyqtSignal()
    next_requested = pyqtSignal()
    prev_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)

        # Иконка — рисуем программно, чтобы не зависеть от файлов
        self.setIcon(self._make_icon())
        self.setToolTip("YT Music Local")

        # Меню
        menu = QMenu()

        act_show = menu.addAction("Развернуть")
        act_show.triggered.connect(self.show_window_requested.emit)

        menu.addSeparator()

        act_play = menu.addAction("Играть / Пауза")
        act_play.triggered.connect(self.play_pause_requested.emit)

        act_next = menu.addAction("Следующий")
        act_next.triggered.connect(self.next_requested.emit)

        act_prev = menu.addAction("Предыдущий")
        act_prev.triggered.connect(self.prev_requested.emit)

        menu.addSeparator()

        act_quit = menu.addAction("Выход")
        act_quit.triggered.connect(self.quit_requested.emit)

        self.setContextMenu(menu)

        # Двойной клик по иконке — развернуть окно
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.DoubleClick,
                      QSystemTrayIcon.ActivationReason.Trigger):
            self.show_window_requested.emit()

    def _make_icon(self) -> QIcon:
        """Рисует простую иконку-ноту."""
        size = 64
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Фон — круг зелёный
        painter.setBrush(QColor(COLORS['accent_green']))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(4, 4, size - 8, size - 8)

        # Буква ♪
        painter.setPen(QColor("#000000"))
        font = QFont()
        font.setPointSize(30)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "♪")

        painter.end()
        return QIcon(pixmap)

    def show_message(self, title: str, message: str) -> None:
        """Показывает системное уведомление."""
        self.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 3000)