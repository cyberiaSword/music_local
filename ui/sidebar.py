"""
Боковая панель навигации.
"""
import json

from PyQt6.QtCore import pyqtSignal, Qt, QSize
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel, QButtonGroup,
    QListWidget, QListWidgetItem, QAbstractItemView, QMenu,
)


class _PlaylistList(QListWidget):
    tracks_dropped = pyqtSignal(str, list)
    TRACK_IDS_MIME = 'application/x-yt-local-track-ids'

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMaximumHeight(240)
        self.setMinimumHeight(0)

    @classmethod
    def _track_ids(cls, mime_data) -> list[int] | None:
        if not mime_data.hasFormat(cls.TRACK_IDS_MIME):
            return None
        try:
            track_ids = json.loads(
                bytes(mime_data.data(cls.TRACK_IDS_MIME)).decode('utf-8')
            )
        except (UnicodeDecodeError, ValueError):
            return None
        if not isinstance(track_ids, list) or not track_ids:
            return None
        if not all(type(track_id) is int and track_id > 0 for track_id in track_ids):
            return None
        return list(dict.fromkeys(track_ids))

    def dragEnterEvent(self, event) -> None:
        if self._track_ids(event.mimeData()) is not None:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        item = self.itemAt(event.position().toPoint())
        if item is not None and self._track_ids(event.mimeData()) is not None:
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        item = self.itemAt(event.position().toPoint())
        track_ids = self._track_ids(event.mimeData())
        if item is None or track_ids is None:
            event.ignore()
            return
        event.setDropAction(Qt.DropAction.CopyAction)
        event.accept()
        self.tracks_dropped.emit(item.data(Qt.ItemDataRole.UserRole), track_ids)


class Sidebar(QWidget):
    """
    Левая панель с разделами.
    Сигнал section_changed испускается с идентификатором раздела:
        'overview' | 'library' | 'downloads' | 'settings'
    """

    section_changed = pyqtSignal(str)
    playlist_selected = pyqtSignal(str)
    playlist_create_requested = pyqtSignal()
    playlist_rename_requested = pyqtSignal(str)
    playlist_delete_requested = pyqtSignal(str)
    playlist_tracks_dropped = pyqtSignal(str, list)

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
        logo = QLabel("YT Music Local")
        logo.setObjectName("Logo")
        layout.addWidget(logo)

        # Кнопки разделов
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)

        sections = [
            ("overview",  "library",  "Обзор"),
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
            if section_id == 'library':
                self._add_playlist_section(layout)

        self._group.buttons()[0].setChecked(True)

        layout.addStretch()

        # Версия внизу
        version = QLabel("  v0.35 · Python + Qt")
        version.setStyleSheet("color: #6a6a6a; font-size: 11px; padding: 12px;")
        layout.addWidget(version)

    def _add_playlist_section(self, layout: QVBoxLayout) -> None:
        from ui.icons import get_icon
        from ui.styles import COLORS

        self._playlist_toggle = QPushButton("Плейлисты")
        self._playlist_toggle.setIcon(get_icon('library', 18, COLORS['text_secondary']))
        self._playlist_toggle.setCheckable(True)
        self._playlist_toggle.setChecked(True)
        self._playlist_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(self._playlist_toggle)

        self._playlist_content = QWidget(self)
        content_layout = QVBoxLayout(self._playlist_content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        create_button = QPushButton("+ Создать плейлист")
        create_button.setCursor(Qt.CursorShape.PointingHandCursor)
        create_button.clicked.connect(
            lambda _checked=False: self.playlist_create_requested.emit()
        )
        content_layout.addWidget(create_button)

        self._playlists = _PlaylistList(self._playlist_content)
        self._playlists.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._playlists.customContextMenuRequested.connect(self._playlist_menu)
        self._playlists.currentItemChanged.connect(self._on_playlist_changed)
        self._playlists.tracks_dropped.connect(self.playlist_tracks_dropped.emit)
        content_layout.addWidget(self._playlists)
        layout.addWidget(self._playlist_content)
        self._playlist_toggle.toggled.connect(self._playlist_content.setVisible)

    @property
    def section_ids(self) -> tuple[str, ...]:
        """Фактический порядок кнопок для клавиатурной навигации."""
        return tuple(str(button.property('section_id')) for button in self._group.buttons())

    def _clear_playlist_selection(self) -> None:
        blocked = self._playlists.blockSignals(True)
        try:
            self._playlists.setCurrentItem(None)
            self._playlists.clearSelection()
        finally:
            self._playlists.blockSignals(blocked)

    def _on_click(self, section: str) -> None:
        self._clear_playlist_selection()
        self.section_changed.emit(section)

    def set_section(self, section_id: str) -> None:
        """Программно выбирает раздел без испускания section_changed."""
        for btn in self._group.buttons():
            if btn.property('section_id') == section_id:
                self._clear_playlist_selection()
                btn.setChecked(True)
                return

    def set_playlists(self, playlists: list) -> None:
        """Обновляет список объектов с полями id/name, сохраняя выбор по id."""
        current = self._playlists.currentItem()
        selected_id = current.data(Qt.ItemDataRole.UserRole) if current else None
        blocked = self._playlists.blockSignals(True)
        try:
            self._playlists.clear()
            for playlist in playlists:
                item = QListWidgetItem(playlist.name)
                item.setData(Qt.ItemDataRole.UserRole, str(playlist.id))
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsDropEnabled)
                self._playlists.addItem(item)
                if selected_id == str(playlist.id):
                    self._playlists.setCurrentItem(item)
        finally:
            self._playlists.blockSignals(blocked)

    def set_playlist(self, playlist_id: str) -> None:
        """Выбирает существующий плейлист без навигационных сигналов."""
        for row in range(self._playlists.count()):
            item = self._playlists.item(row)
            if item.data(Qt.ItemDataRole.UserRole) != playlist_id:
                continue
            self._group.setExclusive(False)
            for button in self._group.buttons():
                button.setChecked(False)
            self._group.setExclusive(True)
            blocked = self._playlists.blockSignals(True)
            try:
                self._playlists.setCurrentItem(item)
                item.setSelected(True)
                self._playlists.scrollToItem(item)
            finally:
                self._playlists.blockSignals(blocked)
            return

    def _on_playlist_changed(self, current, _previous) -> None:
        if current is None:
            return
        playlist_id = current.data(Qt.ItemDataRole.UserRole)
        self.set_playlist(playlist_id)
        self.playlist_selected.emit(playlist_id)

    def _playlist_menu(self, position) -> None:
        item = self._playlists.itemAt(position)
        if item is None:
            return
        playlist_id = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        rename_action = menu.addAction("Переименовать")
        delete_action = menu.addAction("Удалить")
        action = menu.exec(self._playlists.viewport().mapToGlobal(position))
        if action == rename_action:
            self.playlist_rename_requested.emit(playlist_id)
        elif action == delete_action:
            self.playlist_delete_requested.emit(playlist_id)