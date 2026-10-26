"""
Список треков с обложками, фильтрами и сортировкой.
"""

import hashlib
import logging
from pathlib import Path
from PyQt6.QtGui import QPainterStateGuard

from PyQt6.QtCore import (
    Qt, QAbstractListModel, QModelIndex, QSize, QEvent, QThread, QTimer,
    pyqtSignal, QRect, QVariantAnimation, QEasingCurve
)
from PyQt6.QtGui import (
    QPixmap, QPainter, QColor, QFont, QPen,
    QLinearGradient, QPainterPath
)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QComboBox, QListView, QStyledItemDelegate, QStyle,
    QLabel, QPushButton, QStackedWidget, QMenu
)

from ui.track_actions import TrackListView, read_track_ids

from core.database import Database, Track
from core.cover_cache import CoverCache
from core.paths import get_data_dir
from ui.feedback_widgets import EmptyStateWidget, SkeletonList
from ui.styles import COLORS

logger = logging.getLogger('yt-local.ui.tracks')
PAGE_SIZE = 100


class TrackPageLoader(QThread):
    loaded = pyqtSignal(int, int, object, str)

    def __init__(self, db, request_id, search, sort_by, sort_desc, status, offset,
                 parent=None, playlist_id: str | None = None):
        super().__init__(parent)
        self.db = db
        self.request_id = request_id
        self.search = search
        self.sort_by = sort_by
        self.sort_desc = sort_desc
        self.status = status
        self.offset = offset
        self.playlist_id = playlist_id

    def run(self) -> None:
        if self.isInterruptionRequested():
            return
        try:
            if self.playlist_id is not None:
                tracks = self.db.get_playlist_tracks(
                    self.playlist_id, search=self.search, filter_status=self.status,
                    limit=PAGE_SIZE, offset=self.offset,
                )
            else:
                tracks = self.db.get_all(
                    search=self.search,
                    sort_by=self.sort_by,
                    sort_desc=self.sort_desc,
                    filter_status=self.status,
                    limit=PAGE_SIZE,
                    offset=self.offset,
                )
            if not self.isInterruptionRequested():
                self.loaded.emit(self.request_id, self.offset, tracks, "")
        except Exception as error:
            logger.exception("Ошибка фоновой загрузки страницы библиотеки")
            if not self.isInterruptionRequested():
                self.loaded.emit(self.request_id, self.offset, [], str(error))


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
        self._cover_size = 56
        self._cover_cache = CoverCache(
            get_data_dir() / "cache" / "covers"
        )
        self._playing_video_id: str | None = None
        self._progress: dict[int, int] = {}
        self.load_error = False

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
        if not index.isValid():
            return Qt.ItemFlag.NoItemFlags
        return (Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
                | Qt.ItemFlag.ItemIsDragEnabled)

    def set_queued(self, track_ids: list[int]) -> None:
        previous = getattr(self, '_queued_ids', set())
        self._queued_ids = set(track_ids)
        changed = previous.symmetric_difference(self._queued_ids)
        for row, track in enumerate(self._tracks):
            if track.id in changed:
                index = self.index(row, 0)
                self.dataChanged.emit(index, index)

    def is_queued(self, track_id: int) -> bool:
        return track_id in getattr(self, '_queued_ids', set())

    # ---------- Данные ----------

    def reload(
        self,
        search: str = '',
        sort_by: str = 'last_played',
        sort_desc: bool = True,
        filter_status: str | None = None,
    ) -> None:
        self.beginResetModel()
        self.load_error = False
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
            self.load_error = True
        finally:
            self.endResetModel()

    def replace_page(self, tracks: list[Track], failed: bool = False) -> None:
        self.beginResetModel()
        self._tracks = tracks
        self.load_error = failed
        self.endResetModel()

    def append_page(self, tracks: list[Track]) -> None:
        if not tracks:
            return
        first = len(self._tracks)
        last = first + len(tracks) - 1
        self.beginInsertRows(QModelIndex(), first, last)
        self._tracks.extend(tracks)
        self.endInsertRows()

    def get_track(self, row: int) -> Track | None:
        if 0 <= row < len(self._tracks):
            return self._tracks[row]
        return None

    # ---------- Обложки ----------

    def _get_cover(self, track: Track) -> QPixmap:
        pixmap = None
        if track.cover_path:
            path = Path(track.cover_path)
            if not path.is_absolute():
                path = get_data_dir() / path
            pixmap = self._cover_cache.get(path, self._cover_size)

        if pixmap is None:
            pixmap = self._make_placeholder(track.title, track.video_id)
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
        self._cover_cache.clear_memory()

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
                self._cover_cache.clear_memory()
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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._view = parent
        self._hovered_row = -1
        self._hover_progress = 0.0
        self._hover_animation = QVariantAnimation(self)
        self._hover_animation.setDuration(180)
        self._hover_animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._hover_animation.valueChanged.connect(self._update_hover_progress)
        self._hover_animation.finished.connect(self._finish_hover_animation)
        self._hover_target = 0.0

    def set_hovered_index(self, index) -> None:
        if not index.isValid():
            return
        if index.row() == self._hovered_row and self._hover_target == 1.0:
            return
        if index.row() != self._hovered_row:
            self._hover_progress = 0.0
        self._hovered_row = index.row()
        self._animate_hover(1.0)

    def clear_hovered_index(self) -> None:
        if self._hovered_row < 0:
            return
        self._animate_hover(0.0)

    def _animate_hover(self, target: float) -> None:
        self._hover_animation.stop()
        self._hover_target = target
        self._hover_animation.setStartValue(self._hover_progress)
        self._hover_animation.setEndValue(target)
        self._hover_animation.start()

    def _update_hover_progress(self, value) -> None:
        self._hover_progress = float(value)
        if self._view is not None:
            self._view.viewport().update()

    def _finish_hover_animation(self) -> None:
        if self._hover_target == 0.0:
            self._hovered_row = -1
            if self._view is not None:
                self._view.viewport().update()

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

            self._paint_background(
                painter, rect, is_selected, is_hovered, is_playing, index.row()
            )
            self._paint_cover(painter, rect, cover)
            self._paint_text(painter, rect, track, is_playing)
            self._paint_progress(painter, rect, track, index)
            self._paint_status(painter, rect, track)
            if index.model().is_queued(track.id):
                painter.setPen(QPen(QColor(COLORS['accent_green']), 1.5))
                x = rect.right() - 164
                y = rect.center().y() - 5
                for line in range(3):
                    painter.drawLine(x, y + line * 4, x + 10, y + line * 4)
                painter.drawLine(x + 14, y + 4, x + 14, y + 12)
                painter.drawLine(x + 10, y + 8, x + 18, y + 8)

            if is_hovered and track.download_status == 'done' and not is_playing:
                self._paint_play_button(painter, rect)
        finally:
            guard.restore()


    # ---------- Части отрисовки ----------

    def _paint_background(
        self, painter, rect, is_selected, is_hovered, is_playing, row
    ):
        card_rect = rect.adjusted(4, 2, -4, -2)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 24))
        painter.drawRoundedRect(card_rect.adjusted(0, 3, 0, 1), 11, 11)
        painter.setBrush(QColor(0, 0, 0, 18))
        painter.drawRoundedRect(card_rect.adjusted(0, 1, 0, 0), 11, 11)

        base = QColor(COLORS['bg_secondary'])
        if is_selected:
            bg = QColor(COLORS['bg_elevated'])
        elif row == self._hovered_row:
            target = QColor(COLORS['bg_tertiary'])
            progress = self._hover_progress
            bg = QColor(
                round(base.red() + (target.red() - base.red()) * progress),
                round(base.green() + (target.green() - base.green()) * progress),
                round(base.blue() + (target.blue() - base.blue()) * progress),
            )
        else:
            bg = base

        painter.setBrush(bg)
        painter.drawRoundedRect(card_rect, 10, 10)

        if is_playing:
            painter.setBrush(QColor(COLORS['accent_green']))
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
        painter.setPen(QColor(COLORS['accent_green'] if is_playing else COLORS['text_primary']))

        title_rect = QRect(text_x, rect.top() + 14, text_width, 20)
        display_title = f"{track.title}  ({track.video_id[-4:]})"
        title_text = painter.fontMetrics().elidedText(
            display_title, Qt.TextElideMode.ElideRight, text_width
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
        from ui.icons import get_pixmap

        size = 36
        x = rect.right() - 200
        y = rect.top() + (rect.height() - size) // 2
        btn_rect = QRect(x, y, size, size)

        painter.setBrush(QColor(COLORS['accent_green']))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(btn_rect)
        icon = get_pixmap("play", 16, "#000000")
        painter.drawPixmap(btn_rect.center().x() - 8, btn_rect.center().y() - 8, icon)

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
    clear_search_requested = pyqtSignal()
    enqueue_requested = pyqtSignal(int, str)
    playlist_add_requested = pyqtSignal(str, int)
    playlist_reorder_requested = pyqtSignal(str, list)
    playlist_remove_requested = pyqtSignal(str, int)

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._playlist_id: str | None = None
        self._playlists: list = []
        self._closed = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 16, 24, 16)
        layout.setSpacing(12)

        # ---- Верхняя строка ----
        top = QHBoxLayout()
        top.setSpacing(10)

        self.title = QLabel("Библиотека")
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.title.setObjectName("SectionTitle")
        top.addWidget(self.title)
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
        layout.addLayout(top)

        # ---- Список ----
        self.model = TrackModel(db, self)
        self.view = TrackListView(self)
        self.view.setObjectName("TrackList")
        self.view.setModel(self.model)
        self.view.accept_tracks = self._can_drop_tracks
        self.view.tracks_dropped.connect(self._on_tracks_dropped)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._show_context_menu)
        self.delegate = TrackDelegate(self.view)
        self.view.setItemDelegate(self.delegate)
        self.view.entered.connect(self.delegate.set_hovered_index)
        self.view.viewport().installEventFilter(self)
        self.view.setMouseTracking(True)
        self.view.setUniformItemSizes(True)
        self.view.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.view.setSelectionMode(QListView.SelectionMode.SingleSelection)
        self.view.setSpacing(0)

        self.view.clicked.connect(self._on_clicked)
        self.view.doubleClicked.connect(self._on_double_clicked)

        self.content_stack = QStackedWidget()
        self.content_stack.addWidget(self.view)
        self.empty_state = self._create_empty_state()
        self.empty_state.setAcceptDrops(True)
        self.empty_state.installEventFilter(self)
        self.content_stack.addWidget(self.empty_state)
        self.skeleton = SkeletonList(parent=self)
        self.content_stack.addWidget(self.skeleton)
        layout.addWidget(self.content_stack, stretch=1)

        self._request_id = 0
        self._page_loading = False
        self._has_more = True
        self._workers: set[TrackPageLoader] = set()
        self.view.verticalScrollBar().valueChanged.connect(self._maybe_load_more)
        self._reload()

    # ---------- Обработчики ----------

    def _show_context_menu(self, position) -> None:
        index = self.view.indexAt(position)
        track = self.model.get_track(index.row()) if index.isValid() else None
        if track is None:
            return
        self.view.setCurrentIndex(index)
        playlist_id = self._playlist_id
        menu = QMenu(self)
        next_action = menu.addAction("Играть следующим")
        next_action.triggered.connect(
            lambda: self.enqueue_requested.emit(track.id, 'next'))
        end_action = menu.addAction("Добавить в очередь")
        end_action.triggered.connect(
            lambda: self.enqueue_requested.emit(track.id, 'end'))
        submenu = menu.addMenu("Добавить в плейлист")
        submenu.setEnabled(bool(self._playlists))
        for playlist in self._playlists:
            action = submenu.addAction(playlist.name)
            action.triggered.connect(
                lambda checked=False, target=playlist.id:
                self.playlist_add_requested.emit(target, track.id))
        if playlist_id is not None:
            menu.addSeparator()
            remove_action = menu.addAction("Удалить из плейлиста")
            remove_action.triggered.connect(
                lambda: self.playlist_remove_requested.emit(playlist_id, track.id))
        menu.exec(self.view.viewport().mapToGlobal(position))
        menu.deleteLater()

    def _can_drop_tracks(self, internal: bool) -> bool:
        if self._closed or self._playlist_id is None:
            return False
        if not internal:
            return True
        return (not self._page_loading and not self._has_more
                and not self.model.load_error
                and not getattr(self, '_reorder_pending', False)
                and not getattr(self, '_external_search', '')
                and self.status_combo.currentData() is None)

    def _on_tracks_dropped(self, track_ids: list[int], row: int, internal: bool) -> None:
        if not self._can_drop_tracks(internal):
            return
        playlist_id = self._playlist_id
        if not internal:
            for track_id in track_ids:
                self.playlist_add_requested.emit(playlist_id, track_id)
            return
        current = [self.model.get_track(index).id
                   for index in range(self.model.rowCount())]
        moved = set(track_ids)
        if not moved.issubset(current):
            return
        row = max(0, min(row, len(current)))
        insertion = sum(track_id not in moved for track_id in current[:row])
        remaining = [track_id for track_id in current if track_id not in moved]
        ordered = [track_id for track_id in current if track_id in moved]
        reordered = remaining[:insertion] + ordered + remaining[insertion:]
        if reordered != current:
            self._reorder_pending = True
            self.playlist_reorder_requested.emit(playlist_id, reordered)

    def _reload(self, *_args) -> None:
        if self._closed:
            return
        self._request_id += 1
        self._reorder_pending = False
        self._page_loading = False
        self._has_more = True
        self.model.replace_page([])
        self.content_stack.setCurrentWidget(self.skeleton)
        self.skeleton.start()
        self._start_page_load(0)

    def _start_page_load(self, offset: int) -> None:
        if self._closed:
            return
        sort_by, sort_desc = self.sort_combo.currentData()
        worker = TrackPageLoader(
            self.db,
            self._request_id,
            getattr(self, "_external_search", ""),
            sort_by,
            sort_desc,
            self.status_combo.currentData(),
            offset,
            self,
            playlist_id=self._playlist_id,
        )
        self._page_loading = True
        self._workers.add(worker)
        worker.loaded.connect(self._on_page_loaded)
        worker.finished.connect(lambda current=worker: self._workers.discard(current))
        worker.start()

    def _on_page_loaded(self, request_id: int, offset: int, tracks, error: str) -> None:
        if self._closed or request_id != self._request_id:
            return
        self._page_loading = False
        if error:
            if offset == 0:
                self.model.replace_page([], failed=True)
            else:
                logger.warning("Не удалось загрузить следующую страницу списка")
                self.model.load_error = True
                self._has_more = False
        elif offset == 0:
            self.model.replace_page(tracks)
        else:
            self.model.append_page(tracks)

        self._has_more = self._has_more and len(tracks) == PAGE_SIZE and not error
        if offset == 0:
            self.skeleton.stop()
        self._update_empty_state()
        QTimer.singleShot(0, self._fill_playlist_view)

    def _fill_playlist_view(self) -> None:
        if (not self._closed and self._playlist_id is not None
                and not self._page_loading and self._has_more
                and self.view.verticalScrollBar().maximum() == 0):
            self._start_page_load(self.model.rowCount())

    def _maybe_load_more(self, value: int) -> None:
        scrollbar = self.view.verticalScrollBar()
        if (
            not self._page_loading
            and self._has_more
            and scrollbar.maximum() > 0
            and value >= scrollbar.maximum() - 120
        ):
            self._start_page_load(self.model.rowCount())

    def _create_empty_state(self) -> QWidget:
        state = QWidget()
        state.setObjectName("TrackEmptyState")
        state_layout = QVBoxLayout(state)
        state_layout.setContentsMargins(24, 32, 24, 32)
        state_layout.setSpacing(12)
        state_layout.addStretch()

        self.empty_icon = QLabel()
        self.empty_icon.setFixedSize(48, 48)
        state_layout.addWidget(
            self.empty_icon, alignment=Qt.AlignmentFlag.AlignCenter
        )

        self.empty_title = QLabel()
        self.empty_title.setObjectName("EmptyStateTitle")
        self.empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        state_layout.addWidget(self.empty_title)

        self.empty_description = QLabel()
        self.empty_description.setObjectName("EmptyStateDescription")
        self.empty_description.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_description.setWordWrap(True)
        self.empty_description.setMaximumWidth(440)
        state_layout.addWidget(
            self.empty_description, alignment=Qt.AlignmentFlag.AlignCenter
        )

        self.empty_button = QPushButton()
        self.empty_button.setObjectName("EmptyStateButton")
        self.empty_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.empty_button.clicked.connect(self._on_empty_action)
        state_layout.addWidget(
            self.empty_button, alignment=Qt.AlignmentFlag.AlignCenter
        )
        state_layout.addStretch()
        return state

    def _update_empty_state(self) -> None:
        from ui.icons import get_pixmap

        if self.model.rowCount() > 0:
            self.content_stack.setCurrentWidget(self.view)
            return

        has_filter = bool(getattr(self, "_external_search", ""))
        has_filter = has_filter or self.status_combo.currentData() is not None
        if self.model.load_error:
            icon, title, description, action = (
                "x-circle",
                "Не удалось загрузить плейлист" if self._playlist_id is not None
                else "Не удалось загрузить библиотеку",
                "Проверьте подключение к базе данных и попробуйте снова.",
                "Повторить",
            )
        elif has_filter:
            icon, title, description, action = (
                "search",
                "Ничего не найдено",
                "Измените поисковый запрос или фильтр.",
                "Сбросить фильтры",
            )
        elif self._playlist_id is not None:
            icon, title, description, action = (
                "library",
                "Плейлист пуст. Перетащи треки сюда",
                "Добавляй треки из библиотеки или очереди.",
                "Обновить список",
            )
        else:
            icon, title, description, action = (
                "library",
                "Библиотека пуста",
                "Включите трек на YouTube Music — он появится здесь.",
                "Обновить список",
            )

        self.empty_icon.setPixmap(get_pixmap(icon, 40, COLORS['accent_green']))
        self.empty_title.setText(title)
        self.empty_description.setText(description)
        self.empty_button.setText(action)
        self.content_stack.setCurrentWidget(self.empty_state)

    def _on_empty_action(self) -> None:
        has_filter = bool(getattr(self, "_external_search", ""))
        has_filter = has_filter or self.status_combo.currentData() is not None
        if self.model.load_error or not has_filter:
            self.refresh()
            return
        self.status_combo.setCurrentIndex(0)
        self.clear_search_requested.emit()

    def eventFilter(self, watched, event) -> bool:
        if watched == self.view.viewport() and event.type() == QEvent.Type.Leave:
            self.delegate.clear_hovered_index()
        if watched is getattr(self, 'empty_state', None):
            if event.type() in (QEvent.Type.DragEnter, QEvent.Type.DragMove,
                                QEvent.Type.Drop):
                internal = event.source() is self.view
                track_ids = read_track_ids(event.mimeData())
                if track_ids and self._can_drop_tracks(internal):
                    event.setDropAction(Qt.DropAction.CopyAction)
                    event.accept()
                    if event.type() == QEvent.Type.Drop:
                        self._on_tracks_dropped(track_ids, 0, internal)
                else:
                    event.ignore()
                return True
            if event.type() == QEvent.Type.DragLeave:
                event.accept()
                return True
        return super().eventFilter(watched, event)

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

    def set_playlist(self, playlist_id: str | None) -> None:
        if self._playlist_id == playlist_id:
            return
        self._playlist_id = playlist_id
        self.sort_combo.setEnabled(playlist_id is None)
        self.sort_combo.setVisible(playlist_id is None)
        self._update_playlist_title()
        self._reload()

    def set_playlists(self, playlists: list) -> None:
        self._playlists = list(playlists)
        self._update_playlist_title()

    def _update_playlist_title(self) -> None:
        if self._playlist_id is None:
            self.title.setText("Библиотека")
            return
        playlist = next((item for item in self._playlists
                         if item.id == self._playlist_id), None)
        self.title.setText(playlist.name if playlist is not None else "Плейлист")

    def set_queued(self, track_ids: list[int]) -> None:
        self.model.set_queued(track_ids)

    def refresh(self) -> None:
        self._reload()

    def set_playing(self, video_id: str | None) -> None:
        self.model.set_playing(video_id)

    def set_external_search(self, text: str) -> None:
        self._external_search = text
        self._reload()

    def shutdown(self) -> None:
        self._closed = True
        self._request_id += 1
        self.skeleton.stop()
        for worker in tuple(self._workers):
            worker.requestInterruption()
            worker.wait()
        self._workers.clear()

    def set_track_progress(self, track_id: int, percent: int) -> None:
        self.model.set_progress(track_id, percent)