from ui.widgets import ClickableSlider
from PyQt6.QtCore import QPropertyAnimation, QEasingCurve
"""
Виджет нижнего плеера в стиле Spotify.
"""

import logging

from PyQt6.QtCore import Qt, QSize, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap, QFont, QColor, QIcon
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QSlider, QSizePolicy, QFrame
)

from core.database import Track
from core.player import Player
from ui.styles import COLORS

logger = logging.getLogger('yt-local.ui.player')


def _fmt_time(ms: int) -> str:
    """123456 мс → 2:03"""
    if ms <= 0:
        return "0:00"
    total_sec = ms // 1000
    minutes = total_sec // 60
    seconds = total_sec % 60
    return f"{minutes}:{seconds:02d}"


class PlayerWidget(QFrame):
    """
    Нижняя панель плеера.
    Высота фиксирована — 90 px.
    """
    lyrics_toggled = pyqtSignal(bool)
    def __init__(self, player: Player, parent=None):
        super().__init__(parent)
        self.player = player
        self.setObjectName("PlayerBar")
        self.setFixedHeight(90)

        # Кэш текущей обложки для быстрого доступа
        self._current_track: Track | None = None

        # ---- Раскладка ----
        root = QHBoxLayout(self)
        root.setContentsMargins(16, 10, 16, 10)
        root.setSpacing(16)

        # ===== Слева: обложка + инфо =====
        left = QHBoxLayout()
        left.setSpacing(12)

        self.cover_label = QLabel()
        self.cover_label.setFixedSize(60, 60)
        self.cover_label.setStyleSheet(
            f"background-color: {COLORS['bg_tertiary']};"
            f"border-radius: 6px;"
        )
        left.addWidget(self.cover_label)

        info = QVBoxLayout()
        info.setSpacing(2)

        self.title_label = QLabel("Ничего не играет")
        self.title_label.setStyleSheet(
            f"color: {COLORS['text_primary']};"
            "font-size: 13px; font-weight: 600;"
        )
        self.title_label.setMinimumWidth(200)
        info.addWidget(self.title_label)

        self.channel_label = QLabel("—")
        self.channel_label.setStyleSheet(
            f"color: {COLORS['text_secondary']}; font-size: 11px;"
        )
        info.addWidget(self.channel_label)

        left.addLayout(info)
        left.addStretch()

        root.addLayout(left, stretch=3)

        # ===== Центр: кнопки + прогресс =====
        center = QVBoxLayout()
        center.setSpacing(4)

        # Кнопки управления
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addStretch()

        self.btn_shuffle = self._make_icon_button("shuffle", "Перемешать", toggle=True)
        self.btn_shuffle.clicked.connect(self._on_shuffle_clicked)
        self.btn_prev = self._make_icon_button("skip-back", "Предыдущий")
        self.btn_play = self._make_icon_button("play", "Играть / Пауза", big=True)
        self.btn_next = self._make_icon_button("skip-forward", "Следующий")
        self.btn_repeat = self._make_icon_button("repeat", "Повтор", toggle=True)
        self.btn_repeat.clicked.connect(self._on_repeat_clicked)

        self.btn_prev.clicked.connect(self.player.prev_track)
        self.btn_play.clicked.connect(self.player.play_pause)
        self.btn_next.clicked.connect(self.player.next_track)

        buttons.addWidget(self.btn_shuffle)
        buttons.addWidget(self.btn_prev)
        buttons.addWidget(self.btn_play)
        buttons.addWidget(self.btn_next)
        buttons.addWidget(self.btn_repeat)
        buttons.addStretch()
        center.addLayout(buttons)

        # Прогресс
        progress_row = QHBoxLayout()
        progress_row.setSpacing(10)

        self.time_current = QLabel("0:00")
        self.time_current.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px;"
        )
        self.time_current.setFixedWidth(40)
        self.time_current.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        progress_row.addWidget(self.time_current)

        self.progress = ClickableSlider(Qt.Orientation.Horizontal)
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.progress.sliderMoved.connect(self._on_seek)
        self.progress.sliderPressed.connect(self._on_seek_start)
        self.progress.sliderReleased.connect(self._on_seek_end)
        self.progress.clicked_seek.connect(self._on_clicked_seek)
        self.progress.setCursor(Qt.CursorShape.PointingHandCursor)
        progress_row.addWidget(self.progress, stretch=1)

        self.time_total = QLabel("0:00")
        self.time_total.setStyleSheet(
            f"color: {COLORS['text_muted']}; font-size: 11px;"
        )
        self.time_total.setFixedWidth(40)
        self.time_total.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        progress_row.addWidget(self.time_total)

        center.addLayout(progress_row)

        root.addLayout(center, stretch=5)

        # ===== Справа: громкость =====
        right = QHBoxLayout()
        right.setSpacing(8)
        # Кнопка текста
        self.btn_lyrics = self._make_icon_button("align-left", "Текст песни", toggle=True)
        self.btn_lyrics.setCheckable(True)
        right.insertWidget(0, self.btn_lyrics)   # слева от кнопки громкости

        self.btn_volume = self._make_icon_button("volume-2", "Звук", toggle=True)
        self.btn_volume.clicked.connect(self._on_mute_toggle)
        right.addWidget(self.btn_volume)

        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(self.player.get_volume())
        self.volume.setFixedWidth(100)
        self.volume.setCursor(Qt.CursorShape.PointingHandCursor)
        self.volume.valueChanged.connect(self.player.set_volume)
        right.addWidget(self.volume)

        root.addLayout(right, stretch=2)

        # ---- Подписки на сигналы плеера ----
        self.player.track_changed.connect(self._on_track_changed)
        self.player.position_changed.connect(self._on_position_changed)
        self.player.duration_changed.connect(self._on_duration_changed)
        self.player.state_changed.connect(self._on_state_changed)
        self.player.error_occurred.connect(self._on_error)
        self.player.volume_changed.connect(self._on_volume_changed)
        self.player.shuffle_changed.connect(self._on_shuffle_state)
        self.player.repeat_changed.connect(self._on_repeat_state)

        # ---- Таймер для обновления позиции ----
        # Позиционный сигнал QMediaPlayer иногда приходит неравномерно,
        # поэтому дополнительно опрашиваем раз в 500 мс
        self._pos_timer = QTimer(self)
        self._pos_timer.setInterval(500)
        self._pos_timer.timeout.connect(self._poll_position)
        self._pos_timer.start()

        self._seeking = False
        self._muted = False
        self._prev_volume = self.player.get_volume()
        self.btn_lyrics.toggled.connect(self.lyrics_toggled.emit)

    def _extract_accent_color(self, pixmap: QPixmap) -> str | None:
        """
        Извлекает доминирующий цвет из обложки.
        Возвращает hex-строку или None.
        """
        if pixmap.isNull():
            return None

        # Уменьшаем до 8×8 — это усредняет цвета и ускоряет анализ
        small = pixmap.scaled(
            8, 8,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ).toImage()

        # Собираем средний цвет, отбрасывая слишком тёмные/светлые пиксели
        r_sum = g_sum = b_sum = n = 0
        for y in range(small.height()):
            for x in range(small.width()):
                c = small.pixelColor(x, y)
                brightness = (c.red() + c.green() + c.blue()) / 3
                if 40 < brightness < 220:
                    r_sum += c.red()
                    g_sum += c.green()
                    b_sum += c.blue()
                    n += 1

        if n == 0:
            return None

        r, g, b = r_sum // n, g_sum // n, b_sum // n

        # Слегка повышаем насыщенность, чтобы цвет был заметен
        max_c = max(r, g, b)
        if max_c < 100:
            r, g, b = min(255, r + 40), min(255, g + 40), min(255, b + 40)

        return f"#{r:02x}{g:02x}{b:02x}"

    # ============================================================
    # Построение кнопок
    # ============================================================

    def _make_icon_button(
        self,
        icon_name: str,
        tooltip: str,
        big: bool = False,
        toggle: bool = False,
        color: str | None = None,
    ) -> QPushButton:
        """
        Создаёт кнопку с SVG-иконкой.
        big=True — большая круглая кнопка Play (зелёная).
        """
        from ui.icons import get_icon
        from ui.styles import COLORS

        btn = QPushButton()
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setCheckable(toggle)
        btn.setFlat(True)

        size = 44 if big else 32
        btn.setFixedSize(size, size)

        # Иконка
        icon_size = 20 if big else 16
        icon_color = color or ("#000000" if big else COLORS['text_secondary'])
        btn.setIcon(get_icon(icon_name, icon_size, icon_color))
        btn.setIconSize(QSize(icon_size, icon_size))

        if big:
            bg = COLORS['accent_green']
            bg_hover = COLORS['accent_green_h']
            radius = size // 2
        else:
            bg = "transparent"
            bg_hover = COLORS['bg_elevated']
            radius = 8

        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {bg};
                border: none;
                border-radius: {radius}px;
            }}
            QPushButton:hover {{
                background-color: {bg_hover};
            }}
        """)

        # Запоминаем имя иконки и цвет для дальнейшей смены (play ↔ pause)
        btn._icon_name = icon_name
        btn._icon_color = icon_color
        btn._icon_size = icon_size

        return btn

    def _set_button_icon(self, btn: QPushButton, icon_name: str) -> None:
        """Меняет иконку кнопки (например, play → pause)."""
        from ui.icons import get_icon
        btn._icon_name = icon_name
        btn.setIcon(get_icon(icon_name, btn._icon_size, btn._icon_color))

    # ============================================================
    # Обработчики сигналов плеера
    # ============================================================

    def _on_shuffle_state(self, enabled: bool) -> None:
        self.btn_shuffle.setChecked(enabled)
        self._highlight_button(self.btn_shuffle, enabled)

    def _on_repeat_state(self, mode: str) -> None:
        self.btn_repeat.setChecked(mode != 'off')
        self._highlight_button(self.btn_repeat, mode != 'off')

    def _on_track_changed(self, track: Track) -> None:
        self._current_track = track
        self.title_label.setText(track.title)
        self.channel_label.setText(track.channel or "—")
        self._load_cover(track)

    def _on_position_changed(self, pos_ms: int) -> None:
        if self._seeking:
            return
        dur = self.player.duration()
        if dur > 0:
            self.progress.setValue(int(pos_ms * 1000 / dur))
        self.time_current.setText(_fmt_time(pos_ms))

    def _on_duration_changed(self, dur_ms: int) -> None:
        self.time_total.setText(_fmt_time(dur_ms))

    def _on_state_changed(self, state: str) -> None:
        if state == 'playing':
            self._set_button_icon(self.btn_play, "pause")
        else:
            self._set_button_icon(self.btn_play, "play")

    def _on_volume_changed(self, vol: int) -> None:
        self.volume.blockSignals(True)
        self.volume.setValue(vol)
        self.volume.blockSignals(False)

        if vol == 0:
            icon_name = "volume-x"
        elif vol < 40:
            icon_name = "volume-1"
        else:
            icon_name = "volume-2"

        self._set_button_icon(self.btn_volume, icon_name)

    def _on_error(self, msg: str) -> None:
        logger.warning(f"Плеер: {msg}")
        self.title_label.setText("Ошибка воспроизведения")
        self.channel_label.setText(msg[:80])
        # Кнопка лайка
        self.btn_like = self._make_icon_button("heart", "В избранное")
        # Чуть больше левого отступа от текста
        self.btn_like.setStyleSheet(self.btn_like.styleSheet() + """
            QPushButton { margin-left: 8px; }
        """)
        left.addWidget(self.btn_like)

    def _on_shuffle_clicked(self) -> None:
        enabled = self.player.toggle_shuffle()
        self.btn_shuffle.setChecked(enabled)
        # Визуальный акцент — зелёный цвет иконки, когда включено
        self._highlight_button(self.btn_shuffle, enabled)

    def _on_repeat_clicked(self) -> None:
        mode = self.player.cycle_repeat()
        # Кнопка подсвечена, если режим НЕ off
        self.btn_repeat.setChecked(mode != 'off')
        self._highlight_button(self.btn_repeat, mode != 'off')
        # Меняем tooltip
        tips = {'off': 'Повтор выключен', 'all': 'Повтор всей очереди', 'one': 'Повтор одного трека'}
        self.btn_repeat.setToolTip(tips.get(mode, 'Повтор'))

    # ============================================================
    # Обложка
    # ============================================================

    def _load_cover(self, track: Track) -> None:
        pixmap = None
        if track.cover_path:
            from pathlib import Path
            path = Path(track.cover_path)
            if not path.is_absolute():
                base = Path(__file__).resolve().parent.parent / 'data'
                path = base / path
            if path.exists():
                p = QPixmap(str(path))
                if not p.isNull():
                    pixmap = p.scaled(
                        60, 60,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    # Акцентный цвет — применяем к прогрессу
                    accent = self._extract_accent_color(p)
                    if accent:
                        self._apply_accent(accent)

        if pixmap is None:
            pixmap = self._make_placeholder(track.title)

        self.cover_label.setPixmap(pixmap)

    def _apply_accent(self, color: str) -> None:
        """Меняет цвет прогресс-бара и кнопки Play на акцентный."""
        self.progress.setStyleSheet(f"""
            QSlider::groove:horizontal {{
                height: 4px;
                background: {COLORS['border_light']};
                border-radius: 2px;
            }}
            QSlider::sub-page:horizontal {{
                background: {color};
                border-radius: 2px;
            }}
            QSlider::handle:horizontal {{
                background: {color};
                width: 12px;
                height: 12px;
                margin: -4px 0;
                border-radius: 6px;
            }}
        """)
        self.btn_play.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                border: none;
                border-radius: 22px;
            }}
            QPushButton:hover {{
                background-color: {COLORS['accent_green_h']};
            }}
        """)

    def _make_placeholder(self, title: str) -> QPixmap:
        from PyQt6.QtGui import QPainter, QLinearGradient
        from PyQt6.QtCore import QRect

        size = 60
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        grad = QLinearGradient(0, 0, size, size)
        grad.setColorAt(0.0, QColor("#1DB954"))
        grad.setColorAt(1.0, QColor("#1a4a8a"))
        painter.setBrush(grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, size, size, 6, 6)

        letter = (title.strip()[:1] or "?").upper()
        painter.setPen(QColor("#ffffff"))
        font = QFont()
        font.setPointSize(20)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(QRect(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, letter)

        painter.end()
        return pixmap

    # ============================================================
    # Слайдер прогресса
    # ============================================================

    def _on_seek_start(self) -> None:
        self._seeking = True

    def _on_seek(self, value: int) -> None:
        dur = self.player.duration()
        if dur > 0:
            pos = int(value * dur / 1000)
            self.time_current.setText(_fmt_time(pos))

    def _on_seek_end(self) -> None:
        dur = self.player.duration()
        if dur > 0:
            pos = int(self.progress.value() * dur / 1000)
            self.player.seek(pos)
        self._seeking = False

    def _poll_position(self) -> None:
        """Резервный опрос позиции — на случай, если positionChanged молчит."""
        if self.player.is_playing() and not self._seeking:
            pos = self.player.position()
            dur = self.player.duration()
            if dur > 0:
                self.progress.setValue(int(pos * 1000 / dur))
            self.time_current.setText(_fmt_time(pos))

    # ============================================================
    # Громкость — mute toggle
    # ============================================================

    def _on_mute_toggle(self) -> None:
        if self._muted:
            self.player.set_volume(self._prev_volume)
            self._muted = False
        else:
            self._prev_volume = self.player.get_volume()
            self.player.set_volume(0)
            self._muted = True

    def _on_clicked_seek(self, value: int) -> None:
        """
        Пользователь кликнул по дорожке слайдера.
        value — это 0..1000, надо преобразовать в миллисекунды.
        """
        dur = self.player.duration()
        if dur <= 0:
            return
        pos = int(value * dur / 1000)
        self.player.seek(pos)
        # Сразу обновим подпись времени, не дожидаясь следующего тика
        self.time_current.setText(_fmt_time(pos))
        # И синхронизируем слайдер, чтобы handle визуально остался на месте
        self.progress.setValue(value)

    def _on_clicked_seek(self, value: int) -> None:
        dur = self.player.duration()
        if dur <= 0:
            return

        # Плавная анимация значения слайдера к целевой точке
        anim = QPropertyAnimation(self.progress, b"value", self)
        anim.setDuration(180)                    # 180 мс
        anim.setStartValue(self.progress.value())
        anim.setEndValue(value)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)

        pos = int(value * dur / 1000)
        self.player.seek(pos)
        self.time_current.setText(_fmt_time(pos))

    def _highlight_button(self, btn: QPushButton, active: bool) -> None:
        """Меняет цвет иконки и подсветку кнопки."""
        from ui.icons import get_icon
        from ui.styles import COLORS

        color = COLORS['accent_green'] if active else COLORS['text_secondary']
        icon_name = getattr(btn, '_icon_name', None)
        size = getattr(btn, '_icon_size', 16)
        if icon_name:
            btn.setIcon(get_icon(icon_name, size, color))