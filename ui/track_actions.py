"""Общий MIME-контракт треков и представление с безопасным drag/drop."""

import json
from collections.abc import Callable

from PyQt6.QtCore import QMimeData, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QDrag, QPainter, QPen
from PyQt6.QtWidgets import QListView

from ui.styles import COLORS

TRACK_IDS_MIME = 'application/x-yt-local-track-ids'


def track_ids_mime(track_ids: list[int]) -> QMimeData:
    mime = QMimeData()
    mime.setData(TRACK_IDS_MIME, json.dumps(track_ids).encode('utf-8'))
    return mime


def read_track_ids(mime: QMimeData) -> list[int]:
    if not mime.hasFormat(TRACK_IDS_MIME):
        return []
    try:
        values = json.loads(bytes(mime.data(TRACK_IDS_MIME)).decode('utf-8'))
    except (UnicodeError, ValueError, RecursionError):
        return []
    if not isinstance(values, list) or not values:
        return []
    if any(type(value) is not int or value <= 0 for value in values):
        return []
    return list(dict.fromkeys(values))


class TrackListView(QListView):
    tracks_dropped = pyqtSignal(list, int, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.accept_tracks: Callable[[bool], bool] = lambda internal: False
        self._drop_row = -1
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QListView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.CopyAction)
        self.setDropIndicatorShown(False)

    def startDrag(self, supported_actions) -> None:
        tracks = [index.data(Qt.ItemDataRole.UserRole)
                  for index in sorted(self.selectedIndexes(), key=lambda item: item.row())]
        track_ids = [track.id for track in tracks if track is not None]
        if not track_ids:
            return
        drag = QDrag(self)
        drag.setMimeData(track_ids_mime(track_ids))
        # Не используем стандартный Move: изменения выполняет внешний контроллер.
        drag.exec(Qt.DropAction.CopyAction | Qt.DropAction.MoveAction,
                  Qt.DropAction.CopyAction)

    def _accept_drag(self, event) -> bool:
        internal = event.source() is self
        if not self.accept_tracks(internal) or not read_track_ids(event.mimeData()):
            event.ignore()
            self._clear_drop()
            return False
        event.setDropAction(Qt.DropAction.MoveAction if internal else Qt.DropAction.CopyAction)
        event.accept()
        return True

    def dragEnterEvent(self, event) -> None:
        self._accept_drag(event)

    def dragMoveEvent(self, event) -> None:
        if not self._accept_drag(event):
            return
        position = event.position().toPoint()
        index = self.indexAt(position)
        if index.isValid():
            rect = self.visualRect(index)
            self._drop_row = index.row() + int(position.y() >= rect.center().y())
        else:
            self._drop_row = self.model().rowCount()
        self.viewport().update()
        scrollbar = self.verticalScrollBar()
        if position.y() < 24:
            scrollbar.setValue(scrollbar.value() - 24)
        elif position.y() > self.viewport().height() - 24:
            scrollbar.setValue(scrollbar.value() + 24)

    def dragLeaveEvent(self, event) -> None:
        self._clear_drop()
        event.accept()

    def dropEvent(self, event) -> None:
        if not self._accept_drag(event):
            return
        row = self._drop_row if self._drop_row >= 0 else self.model().rowCount()
        track_ids = read_track_ids(event.mimeData())
        internal = event.source() is self
        self._clear_drop()
        self.tracks_dropped.emit(track_ids, row, internal)

    def _clear_drop(self) -> None:
        self._drop_row = -1
        self.viewport().update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if self._drop_row < 0:
            return
        count = self.model().rowCount()
        if self._drop_row < count:
            y = self.visualRect(self.model().index(self._drop_row, 0)).top()
        elif count:
            y = self.visualRect(self.model().index(count - 1, 0)).bottom() + 1
        else:
            y = 2
        y = max(1, min(y, self.viewport().height() - 2))
        painter = QPainter(self.viewport())
        painter.setPen(QPen(QColor(COLORS['accent_green']), 2))
        painter.drawLine(8, y, self.viewport().width() - 8, y)
        painter.end()
