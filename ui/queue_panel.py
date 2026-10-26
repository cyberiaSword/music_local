"""Панель очереди: изменения списка выполняет внешний контроллер."""

import json

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QDrag, QStandardItem, QStandardItemModel
from PyQt6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QMenu, QPushButton,
    QVBoxLayout, QWidget,
)

from core.database import Track
from ui.track_actions import TrackListView, track_ids_mime

QUEUE_ROW_MIME = 'application/x-yt-local-queue-row'


class _QueueView(TrackListView):
    move_requested = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._drag_row: int | None = None
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)

    def startDrag(self, supported_actions) -> None:
        index = self.currentIndex()
        if not index.isValid():
            return
        track = index.data(Qt.ItemDataRole.UserRole)
        self._drag_row = index.row()
        mime = track_ids_mime([track.id])
        mime.setData(QUEUE_ROW_MIME, json.dumps(self._drag_row).encode('utf-8'))
        drag = QDrag(self)
        drag.setMimeData(mime)
        try:
            # Не вызываем стандартный startDrag: он может удалить исходную строку.
            drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction,
                      Qt.DropAction.CopyAction)
        finally:
            self._drag_row = None
            self._clear_drop()

    def _accept_drag(self, event) -> bool:
        mime = event.mimeData()
        row = None
        if event.source() is self and mime.hasFormat(QUEUE_ROW_MIME):
            try:
                row = json.loads(bytes(mime.data(QUEUE_ROW_MIME)).decode('utf-8'))
            except (UnicodeError, ValueError, RecursionError):
                pass
        if (type(row) is not int or row != self._drag_row
                or not 0 <= row < self.model().rowCount()):
            event.ignore()
            self._clear_drop()
            return False
        event.setDropAction(Qt.DropAction.MoveAction)
        event.accept()
        return True

    def dropEvent(self, event) -> None:
        if not self._accept_drag(event):
            return
        source = self._drag_row
        position = event.position().toPoint()
        index = self.indexAt(position)
        boundary = self.model().rowCount()
        if index.isValid():
            boundary = index.row() + int(
                position.y() >= self.visualRect(index).center().y())
        target = boundary - int(boundary > source)
        self._clear_drop()
        if source != target:
            self.move_requested.emit(source, target)


class QueuePanel(QWidget):
    play_requested = pyqtSignal(int)
    remove_requested = pyqtSignal(int)
    move_requested = pyqtSignal(int, int)
    next_requested = pyqtSignal(int)
    clear_requested = pyqtSignal()
    playlist_add_requested = pyqtSignal(str, int)
    enqueue_requested = pyqtSignal(int, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('LyricsPanel')
        self.setFixedWidth(320)
        self._tracks: list[Track] = []
        self._playlists: list = []
        root = QVBoxLayout(self)
        header = QHBoxLayout()
        title = QLabel('Очередь', self)
        title.setObjectName('SectionTitle')
        header.addWidget(title)
        header.addStretch()
        self.clear_button = QPushButton('Очистить', self)
        self.clear_button.setObjectName('GhostButton')
        self.clear_button.clicked.connect(lambda: self.clear_requested.emit())
        header.addWidget(self.clear_button)
        root.addLayout(header)
        self.placeholder = QLabel(
            'Очередь пуста. Добавь треки через контекстное меню', self)
        self.placeholder.setWordWrap(True)
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.placeholder, 1)
        self.view = _QueueView(self)
        self.view.setAccessibleName('Очередь воспроизведения')
        self.model = QStandardItemModel(self)
        self.view.setModel(self.model)
        self.view.doubleClicked.connect(
            lambda index: self.play_requested.emit(index.row()))
        self.view.move_requested.connect(self.move_requested.emit)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._show_context_menu)
        root.addWidget(self.view, 1)
        self.set_queue([], -1)

    def set_queue(self, tracks: list[Track], current_index: int) -> None:
        # Номер вхождения различает несколько позиций с одинаковым ID.
        selected = self.view.currentIndex().row()
        selection_key = None
        if 0 <= selected < len(self._tracks):
            track_id = self._tracks[selected].id
            occurrence = sum(track.id == track_id
                             for track in self._tracks[:selected])
            selection_key = (track_id, occurrence)
        scroll = self.view.verticalScrollBar().value()
        self.view._drag_row = None
        self.view._clear_drop()
        self._tracks = list(tracks)
        blocked = self.view.blockSignals(True)
        try:
            self.model.clear()
            occurrences: dict[int, int] = {}
            for row, track in enumerate(self._tracks):
                text = track.title
                if track.channel:
                    text += f' — {track.channel}'
                item = QStandardItem(text)
                item.setEditable(False)
                item.setData(track, Qt.ItemDataRole.UserRole)
                item.setToolTip(text)
                font = item.font()
                font.setBold(row == current_index)
                item.setFont(font)
                self.model.appendRow(item)
                occurrence = occurrences.get(track.id, 0)
                occurrences[track.id] = occurrence + 1
                if selection_key == (track.id, occurrence):
                    self.view.setCurrentIndex(self.model.index(row, 0))
        finally:
            self.view.blockSignals(blocked)
        self.view.verticalScrollBar().setValue(scroll)
        empty = not self._tracks
        self.placeholder.setVisible(empty)
        self.view.setVisible(not empty)
        self.clear_button.setEnabled(not empty)

    def set_playlists(self, playlists: list) -> None:
        """Принимает объекты с полями id/name, как Sidebar."""
        self._playlists = list(playlists)

    def _show_context_menu(self, position) -> None:
        index = self.view.indexAt(position)
        if not index.isValid():
            return
        self.view.setCurrentIndex(index)
        row = index.row()
        track = self._tracks[row]
        menu = QMenu(self)
        menu.addAction('Удалить').triggered.connect(
            lambda: self.remove_requested.emit(row))
        menu.addAction('Играть следующим').triggered.connect(
            lambda: self.next_requested.emit(row))
        playlists = menu.addMenu('Добавить в плейлист')
        playlists.setEnabled(bool(self._playlists))
        for playlist in self._playlists:
            playlists.addAction(playlist.name).triggered.connect(
                lambda checked=False, target=str(playlist.id):
                self.playlist_add_requested.emit(target, track.id))
        menu.addAction('Добавить в очередь').triggered.connect(
            lambda: self.enqueue_requested.emit(track.id, 'end'))
        menu.exec(self.view.viewport().mapToGlobal(position))
