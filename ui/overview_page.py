"""Страница обзора с недавно добавленными треками и недельным рейтингом."""

import logging
from pathlib import Path

from PyQt6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QSize, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor, QImageReader, QPainter, QPainterPath, QPixmap
from PyQt6.QtWidgets import (
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from core.database import Database, Playlist, Track
from core.paths import get_data_dir
from ui.styles import COLORS

logger = logging.getLogger("yt-local.ui.overview")


def _rounded_cover(source: QPixmap, title: str, size: int = 96) -> QPixmap:
    result = QPixmap(size, size)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, size, size, 12, 12)
    painter.setClipPath(path)
    if source.isNull():
        painter.fillRect(0, 0, size, size, QColor(COLORS["bg_elevated"]))
        painter.setPen(QColor(COLORS["text_secondary"]))
        painter.drawText(result.rect(), Qt.AlignmentFlag.AlignCenter, title[:1].upper() or "♫")
    else:
        scaled = source.scaled(
            size,
            size,
            Qt.AspectRatioMode.KeepAspectRatioByExpanding,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter.drawPixmap((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
    painter.end()
    return result


class OverviewLoader(QThread):
    loaded = pyqtSignal(int, object, str)

    def __init__(self, db: Database, request_id: int, parent=None):
        super().__init__(parent)
        self.db = db
        self.request_id = request_id

    def run(self) -> None:
        try:
            data = {}
            for name, query in (
                ("recent", lambda: self.db.get_recent_tracks(limit=8)),
                ("downloads", lambda: self.db.get_recent_downloads(limit=8)),
                ("weekly", lambda: self.db.get_top_week(limit=6)),
                ("stats", self.db.get_overview_stats),
                ("resume", self.db.get_playback_state),
            ):
                if self.isInterruptionRequested():
                    return
                data[name] = query()
            data_dir = get_data_dir()
            state = data["resume"]
            if state:
                path = Path(state[0].file_path) if state[0].file_path else None
                if path is not None and not path.is_absolute():
                    path = data_dir / path
                if path is None or path.suffix.lower() != ".mp3" or not path.is_file():
                    data["resume"] = None
            tracks = data["recent"] + data["downloads"]
            tracks += [track for track, _ in data["weekly"]]
            if data["resume"]:
                tracks.append(data["resume"][0])
            covers = {}
            for track in tracks:
                if self.isInterruptionRequested():
                    return
                if not track.cover_path or track.cover_path in covers:
                    continue
                try:
                    path = Path(track.cover_path)
                    if not path.is_absolute():
                        path = data_dir / path
                    reader = QImageReader(str(path))
                    reader.setAutoTransform(True)
                    reader.setScaledSize(QSize(96, 96))
                    covers[track.cover_path] = reader.read()
                except (OSError, ValueError):
                    logger.debug("Не удалось прочитать обложку", exc_info=True)
            data["covers"] = covers
            if not self.isInterruptionRequested():
                self.loaded.emit(self.request_id, data, "")
        except Exception as error:
            logger.exception("Не удалось загрузить обзор")
            self.loaded.emit(self.request_id, {}, str(error))


class OverviewTrackCard(QFrame):
    track_requested = pyqtSignal(object)
    enqueue_requested = pyqtSignal(int, str)
    playlist_add_requested = pyqtSignal(str, int)

    def set_playlists(self, playlists: list[Playlist]) -> None:
        self._playlists = list(playlists)

    def _show_context_menu(self, position: QPoint) -> None:
        menu = QMenu(self)
        next_action = menu.addAction("Играть следующим")
        next_action.triggered.connect(
            lambda: self.enqueue_requested.emit(self.track.id, "next"))
        end_action = menu.addAction("Добавить в очередь")
        end_action.triggered.connect(
            lambda: self.enqueue_requested.emit(self.track.id, "end"))
        submenu = menu.addMenu("Добавить в плейлист")
        submenu.setEnabled(bool(self._playlists))
        for playlist in self._playlists:
            action = submenu.addAction(playlist.name)
            action.triggered.connect(
                lambda checked=False, target=playlist.id:
                self.playlist_add_requested.emit(target, self.track.id))
        menu.exec(self.mapToGlobal(position))
        menu.deleteLater()

    def __init__(self, track: Track, covers: dict, weekly_plays: int | None = None, parent=None):
        super().__init__(parent)
        self.track = track
        self._playlists: list[Playlist] = []
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.setObjectName("OverviewTrackCard")
        self.setFixedSize(144, 196)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(f"Воспроизвести: {track.title}")
        self.setToolTip(track.title)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        image = covers.get(track.cover_path)
        source = QPixmap.fromImage(image) if image is not None else QPixmap()
        cover = QLabel()
        cover.setFixedSize(96, 96)
        cover.setPixmap(_rounded_cover(source, track.title))
        cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(cover, alignment=Qt.AlignmentFlag.AlignCenter)

        title = QLabel(track.title)
        title.setTextFormat(Qt.TextFormat.PlainText)
        title.setToolTip(track.title)
        title.setObjectName("OverviewCardTitle")
        title.setWordWrap(True)
        title.setFixedHeight(30)
        layout.addWidget(title)

        subtitle_text = (
            f"{weekly_plays} прослушиваний за 7 дней"
            if weekly_plays is not None
            else (track.channel or "Исполнитель не указан")
        )
        subtitle = QLabel(subtitle_text)
        subtitle.setTextFormat(Qt.TextFormat.PlainText)
        subtitle.setObjectName("OverviewCardSubtitle")
        subtitle.setWordWrap(True)
        subtitle.setFixedHeight(32)
        subtitle.setToolTip(subtitle_text)
        layout.addWidget(subtitle)

        self.shadow = QGraphicsDropShadowEffect(self)
        self.shadow.setBlurRadius(16)
        self.shadow.setOffset(0, 4)
        self.shadow.setColor(QColor(0, 0, 0, 110))
        self.setGraphicsEffect(self.shadow)
        self._shadow_animation = QPropertyAnimation(self.shadow, b"blurRadius", self)
        self._shadow_animation.setDuration(180)
        self._shadow_animation.setEasingCurve(QEasingCurve.Type.OutCubic)

    def enterEvent(self, event) -> None:
        self._animate_shadow(26)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._animate_shadow(16)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.track_requested.emit(self.track)
            event.accept()
            return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            if not event.isAutoRepeat():
                self.track_requested.emit(self.track)
            event.accept()
            return
        super().keyPressEvent(event)

    def _animate_shadow(self, blur: float) -> None:
        self._shadow_animation.stop()
        self._shadow_animation.setStartValue(self.shadow.blurRadius())
        self._shadow_animation.setEndValue(blur)
        self._shadow_animation.start()


class OverviewPage(QWidget):
    track_play_requested = pyqtSignal(object)
    resume_play_requested = pyqtSignal()
    enqueue_requested = pyqtSignal(int, str)
    playlist_add_requested = pyqtSignal(str, int)

    def set_playlists(self, playlists: list[Playlist]) -> None:
        self._playlists = list(playlists)
        for row in (self._recent_layout, self._downloads_layout,
                    self._weekly_layout, self._resume_layout):
            for index in range(row.count()):
                card = row.itemAt(index).widget()
                if isinstance(card, OverviewTrackCard):
                    card.set_playlists(self._playlists)

    def _connect_card_actions(self, card: OverviewTrackCard) -> None:
        card.set_playlists(self._playlists)
        card.enqueue_requested.connect(self.enqueue_requested)
        card.playlist_add_requested.connect(self.playlist_add_requested)

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self.db = db
        self._playlists: list[Playlist] = []
        self._request_id = 0
        self._worker: OverviewLoader | None = None
        self._pending = False
        self._closed = False
        self._covers = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._scroll = QScrollArea()
        self._scroll.setObjectName("OverviewScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        content = QWidget()
        content.setMinimumWidth(0)
        content.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 18, 16, 18)
        layout.setSpacing(12)
        title = QLabel("Обзор")
        title.setObjectName("SectionTitle")
        layout.addWidget(title)

        self._resume_section = QWidget()
        resume_layout = QVBoxLayout(self._resume_section)
        resume_layout.setContentsMargins(0, 0, 0, 0)
        heading = QLabel("Продолжить слушать")
        heading.setObjectName("OverviewSectionTitle")
        resume_layout.addWidget(heading)
        self._resume_layout = QHBoxLayout()
        self._resume_layout.addStretch()
        resume_layout.addLayout(self._resume_layout)
        self._resume_section.hide()
        layout.addWidget(self._resume_section)
        self._recent_layout = self._make_section(layout, "Недавно добавленные")
        self._downloads_layout = self._make_section(layout, "Недавно скачанные")
        self._weekly_layout = self._make_section(layout, "Топ недели")
        self._make_stats(layout)
        self._message = QLabel("Загружаем подборки…")
        self._message.setWordWrap(True)
        self._message.setObjectName("OverviewMessage")
        layout.addWidget(self._message)
        layout.addStretch()
        self._scroll.setWidget(content)
        outer.addWidget(self._scroll)
        self.refresh()

    def _make_section(self, parent_layout, title: str) -> QHBoxLayout:
        section = QVBoxLayout()
        heading = QLabel(title)
        heading.setObjectName("OverviewSectionTitle")
        heading.setWordWrap(True)
        section.addWidget(heading)
        scroll = QScrollArea()
        scroll.setObjectName("OverviewRowScroll")
        scroll.setFixedHeight(230)
        scroll.setMinimumWidth(0)
        scroll.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        row_widget = QWidget()
        row_widget.setObjectName("OverviewCardsRow")
        row_layout = QHBoxLayout(row_widget)
        row_layout.setSizeConstraint(QHBoxLayout.SizeConstraint.SetMinimumSize)
        row_layout.setContentsMargins(2, 4, 12, 8)
        row_layout.setSpacing(14)
        row_layout.addStretch()
        scroll.setWidget(row_widget)
        section.addWidget(scroll)
        parent_layout.addLayout(section)
        return row_layout

    def _make_stats(self, parent_layout: QVBoxLayout) -> None:
        heading = QLabel("Статистика")
        heading.setObjectName("OverviewSectionTitle")
        parent_layout.addWidget(heading)
        grid = QGridLayout()
        self._stats_labels = {}
        for index, (key, caption) in enumerate((
            ("total", "Всего треков"),
            ("downloaded", "Скачано MP3"),
            ("downloads_bytes", "Размер загрузок"),
            ("free_bytes", "Свободно"),
        )):
            tile = QFrame()
            tile.setObjectName("OverviewStatTile")
            tile.setMinimumWidth(0)
            tile.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            box = QVBoxLayout(tile)
            box.setContentsMargins(10, 8, 10, 8)
            label = QLabel(caption)
            label.setWordWrap(True)
            label.setObjectName("OverviewCardSubtitle")
            value = QLabel("0" if key in ("total", "downloaded") else "Нет данных")
            value.setObjectName("OverviewStatValue")
            value.setWordWrap(True)
            for field in (label, value):
                field.setMinimumWidth(0)
                field.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
                box.addWidget(field)
            self._stats_labels[key] = value
            grid.addWidget(tile, index // 2, index % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        parent_layout.addLayout(grid)

    @staticmethod
    def _format_bytes(value: int | None) -> str:
        if value is None:
            return "Нет данных"
        if value >= 1024 ** 3:
            return f"{value / 1024 ** 3:.1f} ГБ"
        return f"{value / 1024 ** 2:.1f} МБ"

    def refresh(self) -> None:
        if self._closed:
            return
        self._request_id += 1
        if self._worker is not None:
            self._pending = True
            return
        self._start_loader()

    def _start_loader(self) -> None:
        self._pending = False
        worker = OverviewLoader(self.db, self._request_id, self)
        self._worker = worker
        worker.loaded.connect(self._on_loaded)
        worker.finished.connect(self._on_worker_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _on_worker_finished(self) -> None:
        if self.sender() is not self._worker:
            return
        self._worker = None
        if self._pending and not self._closed:
            self._start_loader()

    def _on_loaded(self, request_id: int, data: dict, error: str) -> None:
        if self._closed or request_id != self._request_id:
            return
        if error:
            self._message.setText("Не удалось загрузить обзор. Повторите попытку.")
            self._message.show()
            return
        self._covers = data["covers"]
        for row, items, empty in (
            (self._recent_layout, ((t, None) for t in data["recent"]),
             "Добавьте треки — они появятся здесь."),
            (self._downloads_layout, ((t, None) for t in data["downloads"]),
             "Пока нет скачанных MP3."),
            (self._weekly_layout, iter(data["weekly"]),
             "За последние 7 дней прослушиваний пока нет."),
        ):
            self._clear_cards(row)
            self._add_cards(row, items)
            if row.count() == 1:
                message = QLabel(empty)
                message.setObjectName("OverviewMessage")
                message.setWordWrap(True)
                message.setMinimumWidth(0)
                message.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
                row.insertWidget(0, message, 1)
        self._update_resume(data["resume"])
        for key, label in self._stats_labels.items():
            value = data["stats"].get(key)
            label.setText(self._format_bytes(value) if key.endswith("_bytes")
                          else str(value if value is not None else 0))
        self._message.hide()

    def _update_resume(self, state: tuple[Track, int] | None) -> None:
        self._clear_cards(self._resume_layout)
        self._resume_section.setVisible(state is not None)
        if state is None:
            return
        card = OverviewTrackCard(state[0], self._covers)
        self._connect_card_actions(card)
        card.setFixedHeight(228)
        card.setAccessibleName(f"Продолжить слушать: {state[0].title}")
        card.track_requested.connect(self._request_resume)
        play = QPushButton("▶ Play", card)
        play.setObjectName("OverviewPlayButton")
        play.setAccessibleName("Продолжить слушать")
        play.clicked.connect(self._request_resume)
        card.layout().addWidget(play)
        self._resume_layout.insertWidget(0, card)

    def _request_resume(self) -> None:
        self.resume_play_requested.emit()

    def _add_cards(self, row_layout: QHBoxLayout, items) -> None:
        for track, weekly_plays in items:
            card = OverviewTrackCard(track, self._covers, weekly_plays)
            self._connect_card_actions(card)
            card.track_requested.connect(self.track_play_requested)
            row_layout.insertWidget(row_layout.count() - 1, card)

    @staticmethod
    def _clear_cards(row_layout: QHBoxLayout) -> None:
        while row_layout.count() > 1:
            item = row_layout.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._pending = False
        self._request_id += 1
        if self._worker is not None:
            self._worker.requestInterruption()
            self._worker.wait()

    def closeEvent(self, event) -> None:
        self.shutdown()
        super().closeEvent(event)
