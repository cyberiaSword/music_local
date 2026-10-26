"""Общие виджеты загрузки, пустого состояния и уведомлений."""

from PyQt6.QtCore import QEasingCurve, Qt, QPropertyAnimation, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ui.icons import get_pixmap
from ui.styles import COLORS


class EmptyStateWidget(QWidget):
    action_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SharedEmptyState")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 32, 24, 32)
        layout.setSpacing(12)
        layout.addStretch()

        self.icon = QLabel()
        self.icon.setFixedSize(48, 48)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.icon, alignment=Qt.AlignmentFlag.AlignCenter)

        self.title = QLabel()
        self.title.setObjectName("EmptyStateTitle")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title)

        self.description = QLabel()
        self.description.setObjectName("EmptyStateDescription")
        self.description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.description.setWordWrap(True)
        self.description.setMaximumWidth(440)
        layout.addWidget(self.description, alignment=Qt.AlignmentFlag.AlignCenter)

        self.button = QPushButton()
        self.button.setObjectName("EmptyStateButton")
        self.button.clicked.connect(self.action_requested)
        layout.addWidget(self.button, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addStretch()

    def set_state(self, icon: str, title: str, description: str, action: str) -> None:
        self.icon.setPixmap(get_pixmap(icon, 40, COLORS["accent_green"]))
        self.title.setText(title)
        self.description.setText(description)
        self.button.setText(action)


class SkeletonPlaceholder(QWidget):
    def __init__(self, rows: int = 5, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)
        for _ in range(rows):
            row = QFrame()
            row.setObjectName("SkeletonRow")
            row.setFixedHeight(68)
            layout.addWidget(row)
        layout.addStretch()

        self.opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity)
        self.animation = QPropertyAnimation(self.opacity, b"opacity", self)
        self.animation.setDuration(900)
        self.animation.setStartValue(0.45)
        self.animation.setEndValue(0.9)
        self.animation.setLoopCount(-1)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutSine)

    def start(self) -> None:
        self.show()
        self.animation.start()

    def stop(self) -> None:
        self.animation.stop()
        self.hide()


class SkeletonList(SkeletonPlaceholder):
    def __init__(self, parent=None):
        super().__init__(rows=6, parent=parent)


class ToastWidget(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ToastWidget")
        self.setMaximumWidth(420)
        self.setStyleSheet(
            f"QFrame#ToastWidget {{ background: {COLORS['bg_elevated']}; "
            f"border: 1px solid {COLORS['border_light']}; border-radius: 10px; }}"
        )
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.label.setStyleSheet("padding: 10px 14px; color: #FFFFFF;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.label)

        self.opacity = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.opacity)
        self._fade_in = QPropertyAnimation(self.opacity, b"opacity", self)
        self._fade_out = QPropertyAnimation(self.opacity, b"opacity", self)
        self._fade_out.finished.connect(self.hide)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._hide_message)
        self.hide()

    def show_message(self, message: str) -> None:
        self.label.setText(message)
        self.adjustSize()
        parent = self.parentWidget()
        if parent is not None:
            self.move(
                max(16, parent.width() - self.width() - 24),
                max(16, parent.height() - self.height() - 24),
            )
        self.raise_()
        self.opacity.setOpacity(0.0)
        self.show()
        self._fade_in.stop()
        self._fade_in.setDuration(180)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.start()
        self._timer.start(3000)

    def _hide_message(self) -> None:
        self._fade_out.stop()
        self._fade_out.setDuration(180)
        self._fade_out.setStartValue(self.opacity.opacity())
        self._fade_out.setEndValue(0.0)
        self._fade_out.start()


class Toast(ToastWidget):
    """Короткое всплывающее уведомление с плавным затуханием."""

