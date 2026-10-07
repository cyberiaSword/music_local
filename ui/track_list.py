"""
Список треков с обложками, фильтрами и сортировкой.
"""

import hashlib
import logging
from pathlib import Path
from PyQt6.QtGui import QPainterStateGuard

from PyQt6.QtCore import (
    Qt, QAbstractListModel, QModelIndex, QSize,
    pyqtSignal, QRect, QPoint
)
from PyQt6.QtGui import (
    QPixmap, QPainter, QColor, QFont, QPen,
    QLinearGradient, QPainterPath, QPolygon
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QComboBox, QListView, QStyledItemDelegate, QStyle,
    QLabel
)

from core.database import Database, Track
from ui.styles import COLORS

logger = logging.getLogger('yt-local.ui.tracks')


# ============================================================
# Модель
# ============================================================

class TrackModel(QAbstractListModel):
    """
    Модель списка треков.
    Лениво загружает обложки только для видимых элементов.
    """

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._tracks: list[Track] = []
        self._cover_cache: dict[str, QPixmap] = {}
        self._cover_size = 56
        self._playing_video_id: str | None = None
        self._progress: dict[int, int] = {}   # track_id → percent

    # ---------- QAbstractListModel ----------

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._tracks)

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        track = self._tracks[index.row()]

        if role == Qt.ItemDataRole.DisplayRole:
            return track.title
        if role == Qt.ItemDataRole.UserRole:
            return track
        if role == Qt.ItemDataRole.UserRole + 1:
            return self._get_cover(track)
        return None

    def flags(self, index: QModelIndex):
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    # ---------- Данные ----------

    def reload(
        self,
        search: str = '',
        sort_by: str = 'last_played',
        sort_desc: bool = True,
        filter_status: str | None = None,
    ) -> None:
        self.beginResetModel()
        try:
            self._tracks = self.db.get_all(
                search=search,
                sort_by=sort_by,
                sort_desc=sort_desc,
                filter_status=filter_status,
            )
        except Exception as e:
            logger.exception(f"Ошибка загрузки треков: {e}")
            self._tracks = []
        finally:
            self.endResetModel()

    def get_track(self, row: int) -> Track | None:
        if 0 <= row < len(self._tracks):
            return self._tracks[row]
        return None

    # ---------- Обложки ----------

    def _get_cover(self, track: Track) -> QPixmap:
        key = track.video_id
        if key in self._cover_cache:
            return self._cover_cache[key]

        pixmap = None
        if track.cover_path:
            from core.paths import get_data_dir
            path = Path(track.cover_path)
            if not path.is_absolute():
                path = get_data_dir() / path
            if path.exists():
                ...
                p = QPixmap(str(path))
                if not p.isNull():
                    pixmap = p.scaled(
                        self._cover_size, self._cover_size,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    )

        if pixmap is None:
            pixmap = self._make_placeholder(track.title, track.video_id)

        self._cover_cache[key] = pixmap
        return pixmap

    def _make_placeholder(self, title: str, video_id: str = '') -> QPixmap:
        size = self._cover_size
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)

        seed = (video_id or title or '?').encode('utf-8')
        h = int(hashlib.md5(seed).hexdigest()[:6], 16)
        hue = h % 360

        base = QColor.fromHsl(hue, 140, 90)
        dark = QColor.fromHsl(hue, 160, 55)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        grad = QLinearGradient(0, 0, size, size)
        grad.setColorAt(0.0, base)
        grad.setColorAt(1.0, dark)
        painter.setBrush(grad)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(0, 0, size, size, 6, 6)
        painter.end()
        return pixmap

    def invalidate_cover(self, video_id: str) -> None:
        self._cover_cache.pop(video_id, None)

    def set_playing(self, video_id: str | None) -> None:
        old = self._playing_video_id
        self._playing_video_id = video_id
        for i, t in enumerate(self._tracks):
            if t.video_id in (old, video_id):
                idx = self.index(i, 0)
                self.dataChanged.emit(idx, idx)

    def is_playing(self, video_id: str) -> bool:
        return self._playing_video_id == video_id

    def update_track(self, track_id: int) -> None:
        track = self.db.get_track(track_id)
        if track is None:
            return
        for i, t in enumerate(self._tracks):
            if t.id == track_id:
                self._tracks[i] = track
                idx = self.index(i, 0)
                self.dataChanged.emit(idx, idx)
                self._cover_cache.pop(track.video_id, None)
                return

    def set_progress(self, track_id: int, percent: int) -> None:
        self._progress[track_id] = percent
        for i, t in enumerate(self._tracks):
            if t.id == track_id:
                idx = self.index(i, 0)
                self.dataChanged.emit(idx, idx)
                return

    def get_progress(self, track_id: int) -> int | None:
        return self._progress.get(track_id)

    def clear_progress(self, track_id: int) -> None:
        self._progress.pop(track_id, None)


# ============================================================
# Делегат — рисует одну карточку
# ============================================================

class TrackDelegate(QStyledItemDelegate):
    """Рисует карточку трека: обложка, название, канал, статус, прогресс."""

    ROW_HEIGHT = 72
    COVER_SIZE = 56
    PADDING_X = 12

    def sizeHint(self, option, index) -> QSize:
        return QSize(0, self.ROW_HEIGHT)

    def paint(self, painter: QPainter, option, index) -> None:
        track: Track = index.data(Qt.ItemDataRole.UserRole)
        if track is None:
            return
        cover: QPixmap = index.data(Qt.ItemDataRole.UserRole + 1)

        # QPainterStateGuard вызовет save() при создании
        guard = QPainterStateGuard(painter)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

            rect = option.rect
            is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
            is_hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
            is_playing = self._is_playing_track(index)

            self._paint_background(painter, rect, is_selected, is_hovered, is_playing)
            self._paint_cover(painter, rect, cover)
            self._paint_text(painter, rect, track, is_playing)
            self._paint_progress(painter, rect, track, index)
            self._paint_status(painter, rect, track)

            if is_hovered and track.download_status == 'done' and not is_playing:
                self._paint_play_button(painter, rect)
        finally:
            guard.restore()


    # ---------- Части отрисовки ----------

    def _paint_background(self, painter, rect, is_selected, is_hovered, is_playing):
        if is_selected:
            bg = QColor(COLORS['bg_elevated'])
        elif is_hovered:
            bg = QColor(COLORS['bg_tertiary'])
        else:
            bg = QColor(COLORS['bg_secondary'])

        painter.setBrush(bg)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect.adjusted(4, 2, -4, -2), 8, 8)

        if is_playing:
            painter.setBrush(QColor(COLORS['accent_red']))
            painter.drawRoundedRect(
                rect.left() + 4, rect.top() + 12, 3, rect.height() - 24, 2, 2
            )

    def _paint_cover(self, painter, rect, cover):
        cover_x = rect.left() + self.PADDING_X
        cover_y = rect.top() + (rect.height() - self.COVER_SIZE) // 2
        cover_rect = QRect(cover_x, cover_y, self.COVER_SIZE, self.COVER_SIZE)

        if cover and not cover.isNull():
            path = QPainterPath()
            path.addRoundedRect(
                float(cover_rect.x()), float(cover_rect.y()),
                float(cover_rect.width()), float(cover_rect.height()),
                6, 6,
            )
            painter.setClipPath(path)
            painter.drawPixmap(
                cover_rect,
                cover.scaled(
                    self.COVER_SIZE, self.COVER_SIZE,
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                    Qt.TransformationMode.SmoothTransformation,
                ),
            )
            painter.setClipping(False)

    def _paint_text(self, painter, rect, track, is_playing):
        cover_x = rect.left() + self.PADDING_X
        text_x = cover_x + self.COVER_SIZE + 14
        text_width = rect.width() - (text_x - rect.left()) - 200

        # Название
        title_font = QFont()
        title_font.setPointSize(11)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(QColor(COLORS['accent_red'] if is_playing else COLORS['text_primary']))

        title_rect = QRect(text_x, rect.top() + 14, text_width, 20)
        title_text = painter.fontMetrics().elidedText(
            track.title, Qt.TextElideMode.ElideRight, text_width
        )
        painter.drawText(
            title_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            title_text,
        )

        # Канал
        channel_font = QFont()
        channel_font.setPointSize(9)
        painter.setFont(channel_font)
        painter.setPen(QColor(COLORS['text_secondary']))

        channel_rect = QRect(text_x, rect.top() + 36, text_width, 18)
        channel_text = painter.fontMetrics().elidedText(
            track.channel or '—', Qt.TextElideMode.ElideRight, text_width
        )
        painter.drawText(
            channel_rect,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            channel_text,
        )

    def _paint_progress(self, painter, rect, track, index):
        if track.download_status != 'downloading':
            return

        percent = 0
        model = index.model()
        if hasattr(model, 'get_progress'):
            value = model.get_progress(track.id)
            if value is not None:
                percent = value

        bar_y = rect.bottom() - 6
        bar_x = rect.left() + 8
        bar_w = rect.width() - 16
        bar_h = 3

        painter.setBrush(QColor(COLORS['border_light']))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(bar_x, bar_y, bar_w, bar_h, 1.5, 1.5)

        filled_w = int(bar_w * percent / 100)
        if filled_w > 0:
            painter.setBrush(QColor(COLORS['accent_green']))
            painter.drawRoundedRect(bar_x, bar_y, filled_w, bar_h, 1.5, 1.5)

        painter.setPen(QColor(COLORS['text_secondary']))
        font = QFont()
        font.setPointSize(8)
        painter.setFont(font)
        painter.drawText(
            QRect(rect.right() - 60, bar_y - 14, 50, 12),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            f"{percent}%",
        )

    def _paint_status(self, painter, rect, track):
        """Справа — SVG-иконка статуса + количество проигрываний."""
        from ui.status_icons import get_status_pixmap

        pixmap = get_status_pixmap(track.download_status, 18)
        icon_x = rect.right() - 140
        icon_y = rect.top() + (rect.height() - 18) // 2
        if pixmap and not pixmap.isNull():
            painter.drawPixmap(icon_x, icon_y, pixmap)

        plays_font = QFont()
        plays_font.setPointSize(9)
        painter.setFont(plays_font)
        painter.setPen(QColor(COLORS['text_muted']))

        plays_rect = QRect(icon_x + 24, rect.top(), 90, rect.height())
        painter.drawText(
            plays_rect,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            f"{track.play_count} ×",
        )

    def _paint_play_button(self, painter, rect):
        size = 36
        x = rect.right() - 200
        y = rect.top() + (rect.height() - size) // 2
        btn_rect = QRect(x, y, size, size)

        painter.setBrush(QColor(COLORS['accent_green']))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(btn_rect)

        cx, cy = btn_rect.center().x(), btn_rect.center().y()
        triangle = QPolygon([
            QPoint(cx - 5, cy - 7),
            QPoint(cx - 5, cy + 7),
            QPoint(cx + 8, cy),
        ])
        painter.setBrush(QColor("#000000"))
        painter.drawPolygon(triangle)

    def _is_playing_track(self, index) -> bool:
        model = index.model()
        if hasattr(model, 'is_playing'):
            track = index.data(Qt.ItemDataRole.UserRole)
            return bool(track and model.is_playing(track.video_id))
        return False


# ============================================================
# Виджет
# ============================================================

class TrackListWidget(QWidget):
    """Композитный виджет: фильтры + список."""

    track_activated = pyqtSignal(object)
    track_double_clicked = pyqtSignal(object)
    track_play_requested = pyqtSignal(object)

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(12)

        # ---- Верхняя строка ----
        top = QHBoxLayout()
        top.setSpacing(10)

        title = QLabel("Библиотека")
        title.setObjectName("SectionTitle")
        top.addWidget(title)
        top.addStretch()

        # Сортировка
        self.sort_combo = QComboBox()
        self.sort_combo.addItem("Сначала новые", ("last_played", True))
        self.sort_combo.addItem("Сначала старые", ("last_played", False))
        self.sort_combo.addItem("По названию A→Z", ("title", False))
        self.sort_combo.addItem("По названию Z→A", ("title", True))
        self.sort_combo.addItem("По исполнителю", ("channel", False))
        self.sort_combo.addItem("Часто слушаемые", ("play_count", True))
        self.sort_combo.currentIndexChanged.connect(self._reload)
        top.addWidget(self.sort_combo)

        # Фильтр по статусу
        from ui.status_icons import get_status_icon

        self.status_combo = QComboBox()
        self.status_combo.addItem("Все", None)
        self.status_combo.addItem(get_status_icon("pending", 14),     "В очереди",   "pending")
        self.status_combo.addItem(get_status_icon("downloading", 14), "Скачивается", "downloading")
        self.status_combo.addItem(get_status_icon("done", 14),        "Скачано",     "done")
        self.status_combo.addItem(get_status_icon("failed", 14),      "Ошибка",      "failed")
        self.status_combo.currentIndexChanged.connect(self._reload)
        top.addWidget(self.status_combo)

        # ---- Список ----
        self.model = TrackModel(db, self)
        self.view = QListView()
        self.view.setObjectName("TrackList")
        self.view.setModel(self.model)
        self.view.setItemDelegate(TrackDelegate(self.view))
        self.view.setMouseTracking(True)
        self.view.setUniformItemSizes(True)
        self.view.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.view.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.view.setSpacing(0)

        self.view.clicked.connect(self._on_clicked)
        self.view.doubleClicked.connect(self._on_double_clicked)

        layout.addWidget(self.view, stretch=1)

        self._reload()

    # ---------- Обработчики ----------

    def _reload(self, *_args) -> None:
        search = ''
        if hasattr(self, '_external_search'):
            search = self._external_search

        sort_by, sort_desc = self.sort_combo.currentData()
        status = self.status_combo.currentData()
        self.model.reload(
            search=search,
            sort_by=sort_by,
            sort_desc=sort_desc,
            filter_status=status,
        )

    def _on_clicked(self, index) -> None:
        track = self.model.get_track(index.row())
        if track:
            self.track_activated.emit(track)

    def _on_double_clicked(self, index) -> None:
        track = self.model.get_track(index.row())
        if track:
            self.track_double_clicked.emit(track)
            self.track_play_requested.emit(track)

    # ---------- Публичный API ----------

    def refresh(self) -> None:
        self._reload()

    def set_playing(self, video_id: str | None) -> None:
        self.model.set_playing(video_id)

    def set_external_search(self, text: str) -> None:
        self._external_search = text
        self._reload()

    def set_track_progress(self, track_id: int, percent: int) -> None:
        self.model.set_progress(track_id, percent)