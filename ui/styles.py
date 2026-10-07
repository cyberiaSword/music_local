from PyQt6.QtWidgets import QSlider, QStyle, QStyleOptionSlider
"""
QSS-стили и цветовая палитра приложения.
"""

# ---------------- Палитра ----------------

COLORS = {
    # Фоны
    "bg_base":        "#0a0a0a",   # самый тёмный — фон окна
    "bg_primary":     "#121212",   # основной фон контента
    "bg_secondary":   "#181818",   # карточки, sidebar
    "bg_tertiary":    "#1f1f1f",   # ховеры, выделение
    "bg_elevated":    "#242424",   # активные элементы

    # Текст
    "text_primary":   "#ffffff",
    "text_secondary": "#b3b3b3",
    "text_muted":     "#6a6a6a",

    # Акценты
    "accent_green":   "#1DB954",   # Spotify green
    "accent_green_h": "#1ed760",
    "accent_red":     "#FF0000",   # YouTube red (активный трек)
    "accent_blue":    "#3EA6FF",   # YouTube Music blue

    # Границы
    "border":         "#2a2a2a",
    "border_light":   "#333333",
}


def build_stylesheet() -> str:
    """Возвращает QSS-стили для всего приложения."""
    c = COLORS
    return f"""
    /* ============ Базовое ============ */
    QMainWindow, QWidget {{
        background-color: {c['bg_primary']};
        color: {c['text_primary']};
        font-family: "Segoe UI", "SF Pro Display", "Roboto", sans-serif;
        font-size: 13px;
    }}

    QLabel {{
        color: {c['text_primary']};
        background: transparent;
    }}

    /* ============ Sidebar ============ */
    #Sidebar {{
        background-color: {c['bg_base']};
        border-right: 1px solid {c['border']};
    }}

    #Sidebar QLabel#Logo {{
        font-size: 20px;
        font-weight: 700;
        color: {c['accent_green']};
        padding: 20px 18px 10px 18px;
    }}

    #Sidebar QPushButton {{
        background: transparent;
        color: {c['text_secondary']};
        border: none;
        border-radius: 6px;
        padding: 10px 16px;
        text-align: left;
        font-size: 14px;
        font-weight: 500;
    }}

    #Sidebar QPushButton:hover {{
        background-color: {c['bg_tertiary']};
        color: {c['text_primary']};
    }}

    #Sidebar QPushButton:checked {{
        background-color: {c['bg_elevated']};
        color: {c['text_primary']};
        font-weight: 600;
    }}

    /* ============ Заголовки ============ */
    QLabel#SectionTitle {{
        font-size: 24px;
        font-weight: 700;
        color: {c['text_primary']};
    }}

    QLabel#SectionSubtitle {{
        font-size: 12px;
        color: {c['text_muted']};
    }}

    /* ============ Поля ввода ============ */
    QLineEdit {{
        background-color: {c['bg_tertiary']};
        border: 1px solid {c['border']};
        border-radius: 20px;
        padding: 8px 16px;
        color: {c['text_primary']};
        selection-background-color: {c['accent_green']};
    }}

    QLineEdit:focus {{
        border: 1px solid {c['accent_green']};
    }}

    QLineEdit::placeholder {{
        color: {c['text_muted']};
    }}

    /* ============ Выпадающие списки ============ */
    QComboBox {{
        background-color: {c['bg_tertiary']};
        border: 1px solid {c['border']};
        border-radius: 6px;
        padding: 7px 12px;
        color: {c['text_primary']};
        min-width: 140px;
    }}

    QComboBox:hover {{
        background-color: {c['bg_elevated']};
    }}

    QComboBox::drop-down {{
        border: none;
        width: 20px;
    }}

    QComboBox QAbstractItemView {{
        background-color: {c['bg_elevated']};
        border: 1px solid {c['border']};
        color: {c['text_primary']};
        selection-background-color: {c['accent_green']};
        selection-color: #000;
        outline: none;
        padding: 4px;
    }}

    /* ============ Кнопки ============ */
    QPushButton#PrimaryButton {{
        background-color: {c['accent_green']};
        color: #000;
        border: none;
        border-radius: 20px;
        padding: 9px 22px;
        font-weight: 600;
        font-size: 13px;
    }}

    QPushButton#PrimaryButton:hover {{
        background-color: {c['accent_green_h']};
    }}

    QPushButton#PrimaryButton:pressed {{
        background-color: #19a04a;
    }}

    QPushButton#GhostButton {{
        background: transparent;
        color: {c['text_secondary']};
        border: 1px solid {c['border_light']};
        border-radius: 18px;
        padding: 7px 16px;
    }}

    QPushButton#GhostButton:hover {{
        color: {c['text_primary']};
        border-color: {c['text_secondary']};
    }}

    /* ============ Список треков ============ */
    QListView#TrackList {{
        background-color: transparent;
        border: none;
        outline: none;
    }}

    QListView#TrackList::item {{
        border: none;
    }}

    QListView#TrackList::item:selected {{
        background: transparent;
    }}

    /* ============ Скроллбары ============ */
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 0;
    }}

    QScrollBar::handle:vertical {{
        background: {c['border_light']};
        border-radius: 5px;
        min-height: 30px;
    }}

    QScrollBar::handle:vertical:hover {{
        background: {c['text_muted']};
    }}

    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}

    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}

    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
    }}

    QScrollBar::handle:horizontal {{
        background: {c['border_light']};
        border-radius: 5px;
        min-width: 30px;
    }}

    /* ============ Статусбар ============ */
    QStatusBar {{
        background-color: {c['bg_base']};
        color: {c['text_secondary']};
        border-top: 1px solid {c['border']};
    }}

    QStatusBar::item {{
        border: none;
    }}

    /* ============ Тултипы ============ */
    QToolTip {{
        background-color: {c['bg_elevated']};
        color: {c['text_primary']};
        border: 1px solid {c['border_light']};
        padding: 4px 8px;
        border-radius: 4px;
    }}

    /* ============ Меню ============ */
    QMenu {{
        background-color: {c['bg_elevated']};
        color: {c['text_primary']};
        border: 1px solid {c['border']};
        padding: 4px;
    }}

    QMenu::item {{
        padding: 6px 24px 6px 12px;
        border-radius: 4px;
    }}

    QMenu::item:selected {{
        background-color: {c['accent_green']};
        color: #000;
    }}

    QMenu::separator {{
        height: 1px;
        background: {c['border']};
        margin: 4px 8px;
    }}
      /* ============ Нижний плеер ============ */
    QFrame#PlayerBar {{
        background-color: {c['bg_base']};
        border-top: 1px solid {c['border']};
    }}

    QFrame#PlayerBar QLabel {{
        background: transparent;
    }}

    QFrame#PlayerBar QSlider::groove:horizontal {{
        height: 4px;
        background: {c['border_light']};
        border-radius: 2px;
    }}

    QFrame#PlayerBar QSlider::sub-page:horizontal {{
        background: {c['accent_green']};
        border-radius: 2px;
    }}

    QFrame#PlayerBar QSlider::handle:horizontal {{
        background: {c['text_primary']};
        width: 12px;
        height: 12px;
        margin: -4px 0;
        border-radius: 6px;
    }}

    QFrame#PlayerBar QSlider::handle:horizontal:hover {{
        background: {c['accent_green_h']};
    }}

    QFrame#PlayerBar QSlider::add-page:horizontal {{
        background: {c['border_light']};
        border-radius: 2px;
    }}
        /* ============ Кнопки плеера ============ */
    QFrame#PlayerBar QPushButton {{
        background: transparent;
        border: none;
    }}

    /* Тень под плеером через border-top */
    QFrame#PlayerBar {{
        border-top: 2px solid {c['bg_tertiary']};
    }}

    /* Заголовок трека в плеере */
    QFrame#PlayerBar QLabel#PlayerTitle {{
        font-size: 13px;
        font-weight: 600;
        color: {c['text_primary']};
    }}

    QFrame#PlayerBar QLabel#PlayerChannel {{
        font-size: 11px;
        color: {c['text_secondary']};
    }}

    /* ============ Sidebar — иконки ============ */
    #Sidebar QPushButton {{
        padding-left: 12px;
        font-size: 13px;
    }}

    #Sidebar QPushButton QIcon {{
        margin-right: 8px;
    }}
        /* ============ Кастомный заголовок ============ */
    #TitleBar {{
        background-color: {c['bg_base']};
        border-bottom: 1px solid {c['border']};
    }}

    #TitleBarLogo {{
        color: {c['accent_green']};
        font-size: 14px;
        font-weight: 700;
        padding: 0 8px;
    }}

    #TitleBar QLineEdit {{
        background-color: {c['bg_tertiary']};
        border: 1px solid {c['border']};
        border-radius: 16px;
        padding: 6px 14px;
        color: {c['text_primary']};
        font-size: 12px;
    }}

    #TitleBar QLineEdit:focus {{
        border: 1px solid {c['accent_green']};
    }}

    /* ============ Карточка трека ============ */
    QListView#TrackList {{
        background-color: transparent;
    }}

    QListView#TrackList::item {{
        padding: 0;
        margin: 0;
    }}

        /* ============ Диалог настроек ============ */
    QDialog {{
        background-color: {c['bg_primary']};
        color: {c['text_primary']};
    }}

    /* Вкладки */
    QTabWidget::pane {{
        border: 1px solid {c['border']};
        border-radius: 8px;
        background-color: {c['bg_secondary']};
        top: -1px;
    }}

    QTabBar {{
        background-color: transparent;
    }}

    QTabBar::tab {{
        background-color: {c['bg_tertiary']};
        color: {c['text_secondary']};
        padding: 8px 18px;
        margin-right: 2px;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        font-weight: 500;
    }}

    QTabBar::tab:hover {{
        background-color: {c['bg_elevated']};
        color: {c['text_primary']};
    }}

    QTabBar::tab:selected {{
        background-color: {c['bg_secondary']};
        color: {c['accent_green']};
        border-bottom: 2px solid {c['accent_green']};
    }}

    /* Группы */
    QGroupBox {{
        background-color: {c['bg_secondary']};
        color: {c['text_primary']};
        border: 1px solid {c['border']};
        border-radius: 8px;
        margin-top: 14px;
        padding-top: 16px;
        font-weight: 600;
    }}

    QGroupBox::title {{
        color: {c['text_primary']};
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 12px;
        padding: 0 6px;
        background-color: {c['bg_primary']};
    }}

    /* Все лейблы в диалоге */
    QDialog QLabel {{
        color: {c['text_primary']};
        background: transparent;
    }}

    /* Подсказки-описания */
    QDialog QLabel#Hint {{
        color: {c['text_muted']};
        font-size: 11px;
    }}

    /* Чекбоксы */
    QCheckBox {{
        color: {c['text_primary']};
        spacing: 8px;
    }}

    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 4px;
        border: 1px solid {c['border_light']};
        background-color: {c['bg_tertiary']};
    }}

    QCheckBox::indicator:hover {{
        border-color: {c['accent_green']};
    }}

    QCheckBox::indicator:checked {{
        background-color: {c['accent_green']};
        border-color: {c['accent_green']};
    }}

    /* SpinBox */
    QSpinBox {{
        background-color: {c['bg_tertiary']};
        color: {c['text_primary']};
        border: 1px solid {c['border']};
        border-radius: 6px;
        padding: 6px 10px;
        min-width: 80px;
    }}

    QSpinBox:focus {{
        border-color: {c['accent_green']};
    }}

    QSpinBox::up-button, QSpinBox::down-button {{
        background-color: {c['bg_elevated']};
        border: none;
        width: 18px;
    }}

    QSpinBox::up-arrow {{
        image: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-bottom: 5px solid {c['text_secondary']};
        width: 0;
        height: 0;
    }}

    QSpinBox::down-arrow {{
        image: none;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid {c['text_secondary']};
        width: 0;
        height: 0;
    }}

    /* Ползунок прогресса оптимизации */
    QProgressBar {{
        background-color: {c['bg_tertiary']};
        border: none;
        border-radius: 6px;
        text-align: center;
        color: {c['text_primary']};
        height: 18px;
    }}

    QProgressBar::chunk {{
        background-color: {c['accent_green']};
        border-radius: 6px;
    }}

    /* Кнопки в диалоге — наследуют PrimaryButton/GhostButton, но уточним */
    QDialog QPushButton {{
        font-size: 13px;
    }}
    """
"""
Кастомные виджеты.
"""

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QSlider, QStyle


class ClickableSlider(QSlider):
    """
    QSlider, который перематывает по клику на дорожку,
    а не только по перетаскиванию бегунка.

    Сигнал clicked_seek испускается, когда пользователь кликнул
    по дорожке (не по бегунку) — с новым значением в диапазоне
    слайдера (0..maximum()).
    """

    clicked_seek = pyqtSignal(int)

    def __init__(self, orientation=Qt.Orientation.Horizontal, parent=None):
        super().__init__(orientation, parent)

    def mousePressEvent(self, event):
        # ЛКМ по дорожке — сразу перематываем
        if event.button() == Qt.MouseButton.LeftButton:
            value = self._value_from_position(event.position().toPoint())

            # Проверяем, попал ли клик в бегунок.
            # Если да — отдаём событие базовому классу (обычное перетаскивание).
            handle_rect = self._handle_rect()
            if handle_rect.contains(event.position().toPoint()):
                super().mousePressEvent(event)
                return

            # Клик по дорожке — устанавливаем значение
            self.setSliderDown(True)
            self.setValue(value)
            self.clicked_seek.emit(value)
            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # Перетаскивание — базовое поведение
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.isSliderDown():
            self.setSliderDown(False)
        super().mouseReleaseEvent(event)

    # ---- Внутренние утилиты ----

    def _value_from_position(self, pos) -> int:
        """Преобразует координату клика в значение слайдера."""
        if self.orientation() == Qt.Orientation.Horizontal:
            # Учитываем отступы стиля (обычно около 0-2 пикселей)
            groove = self._groove_rect()
            if groove.width() == 0:
                return self.minimum()
            # Позиция относительно начала groove
            x = max(0, min(pos.x() - groove.left(), groove.width()))
            ratio = x / groove.width()
        else:
            groove = self._groove_rect()
            if groove.height() == 0:
                return self.minimum()
            y = max(0, min(pos.y() - groove.top(), groove.height()))
            # Вертикальный слайдер: сверху — максимум, снизу — минимум
            ratio = 1.0 - (y / groove.height())

        value = self.minimum() + round(ratio * (self.maximum() - self.minimum()))
        return max(self.minimum(), min(self.maximum(), value))

    def _groove_rect(self):
        """Возвращает прямоугольник дорожки (groove) с учётом стиля."""
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        return self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            opt,
            QStyle.SubControl.SC_SliderGroove,
            self,
        )

    def _handle_rect(self):
        """Возвращает прямоугольник бегунка (handle)."""
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        return self.style().subControlRect(
            QStyle.ComplexControl.CC_Slider,
            opt,
            QStyle.SubControl.SC_SliderHandle,
            self,
        )