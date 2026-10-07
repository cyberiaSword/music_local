"""
Кастомные виджеты Qt.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QSlider, QStyle, QStyleOptionSlider


class ClickableSlider(QSlider):
    """
    QSlider, который перематывает по клику на дорожку,
    а не только по перетаскиванию бегунка.
    """

    clicked_seek = pyqtSignal(int)

    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            value = self._value_from_position(event.position().toPoint())

            handle_rect = self._handle_rect()
            if handle_rect.contains(event.position().toPoint()):
                super().mousePressEvent(event)
                return

            self.setSliderDown(True)
            self.setValue(value)
            self.clicked_seek.emit(value)
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isSliderDown():
            self.setSliderDown(False)
        super().mouseReleaseEvent(event)

    def _value_from_position(self, pos) -> int:
        if self.orientation() == Qt.Orientation.Horizontal:
            groove = self._groove_rect()
            if groove.width() == 0:
                return self.minimum()
            x = max(0, min(pos.x() - groove.left(), groove.width()))
            ratio = x / groove.width()
        else:
            groove = self._groove_rect()
            if groove.height() == 0:
                return self.minimum()
            y = max(0, min(pos.y() - groove.top(), groove.height()))
            ratio = 1.0 - (y / groove.height())

        value = self.minimum() + round(ratio * (self.maximum() - self.minimum()))
        return max(self.minimum(), min(self.maximum(), value))

    def _groove_rect(self):
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        return self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            opt,
            QStyle.SubControl.SC_SliderGroove,
            self,
        )

    def _handle_rect(self):
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        return self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            opt,
            QStyle.SubControl.SC_SliderHandle,
            self,
        )