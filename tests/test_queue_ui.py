"""QueuePanel: типизированные данные, сигналы и прямые synthetic DnD events."""

import json
from collections.abc import Iterator
from dataclasses import dataclass

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QMimeData, QPoint, QPointF, Qt
from PyQt6.QtWidgets import QMenu

from core.database import Playlist, Track
from ui.queue_panel import QUEUE_ROW_MIME, QueuePanel
from ui.track_actions import track_ids_mime
from .test_queue import QueueRig, app, rig  # noqa: F401


@dataclass
class SyntheticDrop:
    origin: object
    mime: QMimeData
    point: QPointF
    accepted: bool = False
    action: Qt.DropAction = Qt.DropAction.IgnoreAction

    def source(self) -> object:
        return self.origin

    def mimeData(self) -> QMimeData:
        return self.mime

    def position(self) -> QPointF:
        return self.point

    def setDropAction(self, action: Qt.DropAction) -> None:
        self.action = action

    def accept(self) -> None:
        self.accepted = True

    def ignore(self) -> None:
        self.accepted = False


@pytest.fixture
def panel(rig: QueueRig) -> Iterator[QueuePanel]:
    from PyQt6.QtWidgets import QApplication

    app_instance = QApplication.instance()
    assert app_instance is not None
    widget = QueuePanel()
    widget.resize(320, 500)
    widget.show()
    app_instance.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()
    app_instance.processEvents()


def test_creation_placeholder_and_typed_data(panel: QueuePanel, rig: QueueRig) -> None:
    assert panel.placeholder.isVisible()
    assert not panel.view.isVisible()
    assert not panel.clear_button.isEnabled()
    panel.set_queue([rig.tracks[0], rig.tracks[1], rig.tracks[0]], 2)
    assert not panel.placeholder.isVisible()
    assert panel.view.isVisible()
    assert panel.clear_button.isEnabled()
    assert panel.model.rowCount() == 3
    assert [panel.model.item(row).font().bold() for row in range(3)] == [False, False, True]
    track = panel.model.index(2, 0).data(Qt.ItemDataRole.UserRole)
    assert isinstance(track, Track)
    assert track.id == rig.tracks[0].id
    assert not panel.model.item(2).isEditable()
    assert panel.model.item(2).text() == panel.model.item(2).toolTip()
    panel.set_queue([], -1)
    assert panel.placeholder.isVisible()
    assert not panel.clear_button.isEnabled()


def test_panel_controller_wiring_and_duplicate_selection(
        panel: QueuePanel, rig: QueueRig) -> None:
    rig.controller.queue_changed.connect(panel.set_queue)
    panel.play_requested.connect(rig.controller.play_queue_index)
    panel.clear_requested.connect(rig.controller.clear_queue)
    panel.move_requested.connect(rig.controller.move_in_queue)
    rig.queue(0, 1, 0)
    panel.view.setCurrentIndex(panel.model.index(2, 0))
    panel.view.doubleClicked.emit(panel.model.index(2, 0))
    assert rig.controller.current_index == 2
    assert panel.model.item(2).font().bold()
    assert not panel.model.item(0).font().bold()
    panel.set_queue([rig.tracks[1], rig.tracks[0], rig.tracks[0]], 2)
    assert panel.view.currentIndex().row() == 2
    rig.player.stop()
    assert not any(panel.model.item(row).font().bold() for row in range(3))
    panel.clear_button.click()
    assert rig.controller.queue_ids == []
    assert panel.placeholder.isVisible()


@pytest.mark.parametrize("label,signal,expected", [
    ("Удалить", "remove_requested", (2,)),
    ("Играть следующим", "next_requested", (2,)),
    ("Добавить в очередь", "enqueue_requested", None),
    ("Favorites", "playlist_add_requested", None),
])
def test_context_menu_signals_use_row_or_track_id(
        panel: QueuePanel, rig: QueueRig, monkeypatch: pytest.MonkeyPatch,
        label: str, signal: str, expected: tuple[int, ...] | None) -> None:
    panel.set_queue([rig.tracks[0], rig.tracks[1], rig.tracks[0]], 2)
    panel.set_playlists([Playlist("playlist-1", "Favorites", 0, 0)])
    received: list[tuple[object, ...]] = []
    getattr(panel, signal).connect(lambda *args: received.append(args))

    def execute(menu: QMenu, position: QPoint) -> None:
        actions = list(menu.actions())
        for action in menu.actions():
            if action.menu() is not None:
                actions.extend(action.menu().actions())
        next(action for action in actions if action.text() == label).trigger()

    monkeypatch.setattr(QMenu, "exec", execute)
    point = panel.view.visualRect(panel.model.index(2, 0)).center()
    panel._show_context_menu(point)
    if expected is None:
        expected_args = ((rig.tracks[0].id, "end") if signal == "enqueue_requested"
                         else ("playlist-1", rig.tracks[0].id))
    else:
        expected_args = expected
    assert received == [expected_args]


@pytest.mark.parametrize("source,target,below,expected", [
    (2, 0, False, (2, 0)), (0, 2, True, (0, 2)),
    (1, 1, False, None), (0, None, False, (0, 2)),
])
def test_drop_uses_occurrence_row_not_duplicate_id(
        panel: QueuePanel, rig: QueueRig, source: int, target: int | None,
        below: bool, expected: tuple[int, int] | None) -> None:
    panel.set_queue([rig.tracks[0], rig.tracks[1], rig.tracks[0]], 2)
    view = panel.view
    view.doItemsLayout()
    view._drag_row = source
    mime = track_ids_mime([rig.tracks[0].id])
    mime.setData(QUEUE_ROW_MIME, json.dumps(source).encode("utf-8"))
    point = QPoint(5, view.viewport().height() - 1)
    if target is not None:
        rect = view.visualRect(panel.model.index(target, 0))
        point = QPoint(rect.center().x(), rect.bottom() if below else rect.top())
    event = SyntheticDrop(view, mime, QPointF(point))
    moves: list[tuple[int, int]] = []
    panel.move_requested.connect(lambda old, new: moves.append((old, new)))
    view.dropEvent(event)
    assert event.accepted
    assert event.action == Qt.DropAction.MoveAction
    assert moves == ([] if expected is None else [expected])
    assert panel.model.rowCount() == 3
    assert view._drop_row == -1


@pytest.mark.parametrize("payload,internal", [
    (b"true", True), (b'"2"', True), (b"-1", True), (b"3", True),
    (b"1", True), (b"null", True), (b"{", True), (b"\xff", True), (b"2", False),
])
def test_drop_rejects_untyped_stale_and_external_rows(
        panel: QueuePanel, rig: QueueRig, payload: bytes, internal: bool) -> None:
    panel.set_queue([rig.tracks[0], rig.tracks[1], rig.tracks[0]], 2)
    panel.view._drag_row = 2
    mime = track_ids_mime([rig.tracks[0].id])
    mime.setData(QUEUE_ROW_MIME, payload)
    event = SyntheticDrop(panel.view if internal else object(), mime, QPointF(5, 5))
    moves: list[tuple[int, int]] = []
    panel.move_requested.connect(lambda old, new: moves.append((old, new)))
    panel.view.dropEvent(event)
    assert not event.accepted
    assert moves == []
    assert panel.model.rowCount() == 3
