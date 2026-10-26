"""Плейлисты: настоящие Qt widgets, SQLite и synthetic drag/drop без pytest-qt."""

import os
import time
from dataclasses import dataclass

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
pytest.importorskip('PyQt6')
from PyQt6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QApplication, QMenu, QPushButton

from core.database import Database
from ui import track_list
from ui.sidebar import Sidebar
from ui.track_actions import TRACK_IDS_MIME, track_ids_mime


@pytest.fixture(scope='module')
def app():
    application = QApplication.instance() or QApplication([])
    yield application


def wait_for(app, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(10)
    assert predicate(), 'Истекло ожидание Qt worker'
    app.processEvents()


def settled(app, widget):
    wait_for(app, lambda: not widget._page_loading and not widget._workers)


def ids(widget):
    return [widget.model.get_track(row).id for row in range(widget.model.rowCount())]


def populate(db, count=3):
    track_ids = [db.upsert_from_play({
        'videoId': f'playlist-video-{index}', 'title': f'Track {index:03}',
        'channel': 'Even' if index % 2 == 0 else 'Odd',
        'url': f'https://example.invalid/{index}',
    }) for index in range(count)]
    playlist_id = db.create_playlist('Favorites')
    for index, track_id in enumerate(track_ids):
        db.set_download_status(track_id, 'done' if index % 2 == 0 else 'pending')
        db.add_to_playlist(playlist_id, track_id)
    return playlist_id, track_ids


@dataclass
class Drop:
    origin: object
    mime: QMimeData
    point: QPointF
    kind: QEvent.Type = QEvent.Type.Drop
    accepted: bool = False
    action: Qt.DropAction = Qt.DropAction.IgnoreAction

    def source(self):
        return self.origin

    def mimeData(self):
        return self.mime

    def position(self):
        return self.point

    def type(self):
        return self.kind

    def setDropAction(self, action):
        self.action = action

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.accepted = False


def choose_menu(monkeypatch, label):
    def execute(menu, _position):
        actions = list(menu.actions())
        for action in menu.actions():
            if action.menu() is not None:
                actions.extend(action.menu().actions())
        selected = next(action for action in actions if action.text() == label)
        assert selected.isEnabled()
        selected.trigger()
        return selected
    monkeypatch.setattr(QMenu, 'exec', execute)


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.setattr('core.paths.get_data_dir', lambda: tmp_path)
    monkeypatch.setattr(track_list, 'get_data_dir', lambda: tmp_path)
    return Database(tmp_path / 'playlist-ui.db')


@pytest.fixture
def widget_factory(app, db):
    widgets = []

    def create(playlist_id=None):
        widget = track_list.TrackListWidget(db)
        widgets.append(widget)
        widget.resize(800, 500)
        widget.show()
        settled(app, widget)
        widget.set_playlists(db.list_playlists())
        widget.set_playlist(playlist_id)
        settled(app, widget)
        widget.view.doItemsLayout()
        return widget

    yield create
    for widget in widgets:
        widget.shutdown()
        widget.close()
        widget.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_playlist_pagination_search_status_and_library_sort(app, db, widget_factory):
    playlist_id, track_ids = populate(db, 107)
    db.reorder_playlist(playlist_id, track_ids[::-1])
    widget = widget_factory(playlist_id)
    assert widget.title.text() == 'Favorites'
    assert not widget.sort_combo.isEnabled()
    assert widget.sort_combo.isHidden()
    assert ids(widget) == track_ids[::-1][:100]
    assert widget._has_more
    assert not widget._can_drop_tracks(True)
    widget._start_page_load(widget.model.rowCount())
    settled(app, widget)
    assert ids(widget) == track_ids[::-1]
    assert not widget._has_more
    assert widget._can_drop_tracks(True)
    widget.set_external_search('Even')
    settled(app, widget)
    assert ids(widget) == track_ids[::2][::-1]
    assert not widget._can_drop_tracks(True)
    widget.status_combo.setCurrentIndex(widget.status_combo.findData('pending'))
    settled(app, widget)
    assert ids(widget) == []
    assert widget.empty_title.text() == 'Ничего не найдено'
    widget.set_external_search('')
    settled(app, widget)
    assert ids(widget) == track_ids[1::2][::-1]
    assert not widget._can_drop_tracks(True)
    widget.status_combo.setCurrentIndex(0)
    widget.set_playlist(None)
    widget.sort_combo.setCurrentIndex(2)
    settled(app, widget)
    assert widget.title.text() == 'Библиотека'
    assert widget.sort_combo.isEnabled() and not widget.sort_combo.isHidden()
    assert ids(widget) == track_ids[:100]
    assert not widget._can_drop_tracks(False)


def test_empty_playlist_placeholder_and_filter_reset(app, db, widget_factory):
    playlist_id = db.create_playlist('Empty')
    widget = widget_factory(playlist_id)
    assert widget.content_stack.currentWidget() is widget.empty_state
    assert widget.empty_title.text() == 'Плейлист пуст. Перетащи треки сюда'
    assert widget.empty_state.acceptDrops()
    widget.set_external_search('absent')
    settled(app, widget)
    assert widget.empty_title.text() == 'Ничего не найдено'
    cleared = QSignalSpy(widget.clear_search_requested)
    widget.empty_button.click()
    assert list(cleared) == [[]]


def test_internal_drop_emits_complete_order_once(db, widget_factory):
    playlist_id, track_ids = populate(db, 5)
    widget = widget_factory(playlist_id)
    reordered = QSignalSpy(widget.playlist_reorder_requested)
    dropped = QSignalSpy(widget.view.tracks_dropped)
    rect = widget.view.visualRect(widget.model.index(0, 0))
    event = Drop(widget.view, track_ids_mime(track_ids[2:4]), QPointF(rect.topLeft()))
    widget.view.dragEnterEvent(event)
    widget.view.dragMoveEvent(event)
    assert widget.view._drop_row == 0
    widget.view.dropEvent(event)
    assert event.accepted and event.action == Qt.DropAction.MoveAction
    assert list(dropped) == [[track_ids[2:4], 0, True]]
    assert list(reordered) == [[playlist_id, track_ids[2:4] + track_ids[:2] + track_ids[4:]]]
    assert widget.view._drop_row == -1
    assert ids(widget) == track_ids
    assert [track.id for track in db.get_playlist_tracks(playlist_id)] == track_ids
    widget.view.dropEvent(event)
    assert not event.accepted
    assert len(reordered) == 1


@pytest.mark.parametrize('restriction', ['partial', 'search', 'status'])
def test_reorder_rejected_for_incomplete_or_filtered_view(
        app, db, widget_factory, restriction):
    playlist_id, track_ids = populate(db, 105 if restriction == 'partial' else 5)
    widget = widget_factory(playlist_id)
    if restriction == 'search':
        widget.set_external_search('Track')
    elif restriction == 'status':
        widget.status_combo.setCurrentIndex(widget.status_combo.findData('done'))
    settled(app, widget)
    reordered = QSignalSpy(widget.playlist_reorder_requested)
    event = Drop(widget.view, track_ids_mime([track_ids[0]]), QPointF(5, 5))
    widget.view.dragEnterEvent(event)
    assert not event.accepted
    widget.view.dropEvent(event)
    assert not event.accepted
    assert list(reordered) == []
    assert [track.id for track in db.get_playlist_tracks(playlist_id)] == track_ids


@pytest.mark.parametrize('empty', [False, True])
def test_external_drop_on_list_and_empty_page(app, db, widget_factory, empty):
    source_id, track_ids = populate(db)
    target_id = db.create_playlist('Target') if empty else source_id
    widget = widget_factory(target_id)
    added = QSignalSpy(widget.playlist_add_requested)
    reordered = QSignalSpy(widget.playlist_reorder_requested)
    event = Drop(object(), track_ids_mime([track_ids[1], track_ids[0], track_ids[1]]),
                 QPointF(5, 5), QEvent.Type.DragEnter)
    if empty:
        for kind in (QEvent.Type.DragEnter, QEvent.Type.DragMove, QEvent.Type.Drop):
            event.kind = kind
            assert widget.eventFilter(widget.empty_state, event)
            assert event.accepted
    else:
        widget.set_external_search('Track')
        settled(app, widget)
        widget.view.dragEnterEvent(event)
        assert event.accepted
        widget.view.dropEvent(event)
    assert event.action == Qt.DropAction.CopyAction
    assert list(added) == [[target_id, track_ids[1]], [target_id, track_ids[0]]]
    assert list(reordered) == []


@pytest.mark.parametrize('payload', [b'{', b'\xff', b'null', b'1', b'[true]',
                                     b'[0]', b'[-1]', b'[]', b'[1,"2"]'])
@pytest.mark.parametrize('empty', [False, True])
def test_track_drop_rejects_malformed_mime(db, widget_factory, payload, empty):
    playlist_id, _ = populate(db)
    if empty:
        playlist_id = db.create_playlist('Empty')
    widget = widget_factory(playlist_id)
    added = QSignalSpy(widget.playlist_add_requested)
    mime = QMimeData()
    mime.setData(TRACK_IDS_MIME, payload)
    event = Drop(object(), mime, QPointF(5, 5))
    if empty:
        assert widget.eventFilter(widget.empty_state, event)
    else:
        widget.view.dropEvent(event)
    assert not event.accepted
    assert list(added) == []


@pytest.mark.parametrize('label,signal,tail', [
    ('Играть следующим', 'enqueue_requested', 'next'),
    ('Добавить в очередь', 'enqueue_requested', 'end'),
    ('Favorites', 'playlist_add_requested', None),
    ('Удалить из плейлиста', 'playlist_remove_requested', None),
])
def test_track_context_menu_actions(db, widget_factory, monkeypatch, label, signal, tail):
    playlist_id, track_ids = populate(db)
    widget = widget_factory(playlist_id)
    spy = QSignalSpy(getattr(widget, signal))
    choose_menu(monkeypatch, label)
    point = widget.view.visualRect(widget.model.index(1, 0)).center()
    widget.view.customContextMenuRequested.emit(point)
    expected = [track_ids[1], tail] if tail else [playlist_id, track_ids[1]]
    assert list(spy) == [expected]
    assert widget.view.currentIndex().row() == 1


def test_queue_indicator_changes_only_affected_rows(db, widget_factory):
    playlist_id, track_ids = populate(db)
    widget = widget_factory(playlist_id)
    changed = QSignalSpy(widget.model.dataChanged)
    widget.set_queued([track_ids[1], track_ids[1]])
    assert [widget.model.is_queued(track_id) for track_id in track_ids] == [False, True, False]
    assert [args[0].row() for args in changed] == [1]
    widget.set_queued([track_ids[1]])
    assert len(changed) == 1
    widget.set_queued([track_ids[2]])
    assert [args[0].row() for args in changed] == [1, 1, 2]
    widget.set_queued([])
    assert not any(widget.model.is_queued(track_id) for track_id in track_ids)


@pytest.fixture
def sidebar(app, db):
    populate(db)
    db.create_playlist('Second')
    widget = Sidebar()
    widget.set_playlists(db.list_playlists())
    widget.resize(220, 800)
    widget.show()
    app.processEvents()
    yield widget
    widget.close()
    widget.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_sidebar_actual_sections_create_and_selection(sidebar, db):
    assert sidebar.section_ids == ('overview', 'library', 'downloads', 'settings')
    buttons = sidebar._group.buttons()
    assert [button.property('section_id') for button in buttons] == list(sidebar.section_ids)
    assert [sidebar.layout().indexOf(button) for button in buttons] == sorted(
        sidebar.layout().indexOf(button) for button in buttons)
    assert sidebar.layout().indexOf(buttons[1]) < sidebar.layout().indexOf(
        sidebar._playlist_toggle) < sidebar.layout().indexOf(buttons[2])
    created = QSignalSpy(sidebar.playlist_create_requested)
    selected = QSignalSpy(sidebar.playlist_selected)
    sections = QSignalSpy(sidebar.section_changed)
    next(button for button in sidebar.findChildren(QPushButton)
         if button.text() == '+ Создать плейлист').click()
    assert list(created) == [[]]
    item = sidebar._playlists.item(0)
    playlist_id = item.data(Qt.ItemDataRole.UserRole)
    sidebar._playlists.setCurrentItem(item)
    assert list(selected) == [[playlist_id]]
    assert sidebar._group.checkedButton() is None
    sidebar.set_playlists(db.list_playlists())
    assert sidebar._playlists.currentItem().data(Qt.ItemDataRole.UserRole) == playlist_id
    sidebar.set_playlist(playlist_id)
    assert list(selected) == [[playlist_id]]
    for button, section_id in zip(buttons, sidebar.section_ids):
        button.click()
        assert list(sections)[-1] == [section_id]
        assert sidebar._playlists.currentItem() is None
    sidebar.set_section('library')
    assert len(sections) == 4
    assert buttons[1].isChecked()
    sidebar._playlist_toggle.click()
    assert sidebar._playlist_content.isHidden()
    sidebar._playlist_toggle.click()
    assert not sidebar._playlist_content.isHidden()


@pytest.mark.parametrize('label,signal', [
    ('Переименовать', 'playlist_rename_requested'),
    ('Удалить', 'playlist_delete_requested'),
])
def test_sidebar_menu_actions(sidebar, monkeypatch, label, signal):
    received = QSignalSpy(getattr(sidebar, signal))
    item = sidebar._playlists.item(1)
    playlist_id = item.data(Qt.ItemDataRole.UserRole)
    choose_menu(monkeypatch, label)
    sidebar._playlists.customContextMenuRequested.emit(
        sidebar._playlists.visualItemRect(item).center())
    assert list(received) == [[playlist_id]]


def test_sidebar_external_drop_targets_playlist(sidebar):
    view = sidebar._playlists
    item = view.item(1)
    playlist_id = item.data(Qt.ItemDataRole.UserRole)
    received = QSignalSpy(sidebar.playlist_tracks_dropped)
    event = Drop(object(), track_ids_mime([7, 3]), QPointF(view.visualItemRect(item).center()))
    for handler in (view.dragEnterEvent, view.dragMoveEvent, view.dropEvent):
        handler(event)
        assert event.accepted
        assert event.action == Qt.DropAction.CopyAction
    assert list(received) == [[playlist_id, [7, 3]]]
    event.point = QPointF(-10, -10)
    view.dropEvent(event)
    assert not event.accepted
    assert len(received) == 1


@pytest.mark.parametrize('payload', [None, b'{', b'\xff', b'null', b'1', b'[true]',
                                     b'[1,"2"]', b'[]', b'[0]', b'[-1]'])
def test_sidebar_rejects_malformed_track_mime(sidebar, payload):
    view = sidebar._playlists
    mime = QMimeData()
    if payload is not None:
        mime.setData(TRACK_IDS_MIME, payload)
    event = Drop(object(), mime, QPointF(view.visualItemRect(view.item(0)).center()))
    received = QSignalSpy(sidebar.playlist_tracks_dropped)
    view.dragEnterEvent(event)
    assert not event.accepted
    view.dragMoveEvent(event)
    assert not event.accepted
    view.dropEvent(event)
    assert not event.accepted
    assert list(received) == []


def test_sidebar_deduplicates_track_ids_like_track_list(sidebar):
    view = sidebar._playlists
    item = view.item(0)
    received = QSignalSpy(sidebar.playlist_tracks_dropped)
    event = Drop(object(), track_ids_mime([7, 3, 7]),
                 QPointF(view.visualItemRect(item).center()))
    view.dropEvent(event)
    assert event.accepted
    assert list(received) == [[item.data(Qt.ItemDataRole.UserRole), [7, 3]]]


def test_status_filter_is_applied_before_pagination(app, db, widget_factory):
    playlist_id, track_ids = populate(db, 207)
    widget = widget_factory(playlist_id)
    widget.status_combo.setCurrentIndex(widget.status_combo.findData('done'))
    settled(app, widget)
    expected = track_ids[::2]
    assert ids(widget) == expected[:100]
    assert widget._has_more
    widget._start_page_load(widget.model.rowCount())
    settled(app, widget)
    assert ids(widget) == expected
    assert not widget._has_more
    assert not widget._can_drop_tracks(True)


def test_menu_without_playlists_disables_add_and_empty_hit_does_nothing(
        db, widget_factory, monkeypatch):
    _, track_ids = populate(db)
    widget = widget_factory()
    widget.set_playlists([])
    menus = []

    def execute(menu, _position):
        menus.append(menu)
        submenu_action = next(action for action in menu.actions() if action.menu() is not None)
        assert not submenu_action.isEnabled()
        assert submenu_action.menu().actions() == []
        assert 'Удалить из плейлиста' not in [action.text() for action in menu.actions()]

    monkeypatch.setattr(QMenu, 'exec', execute)
    widget._show_context_menu(QPoint(-10, -10))
    assert menus == []
    widget._show_context_menu(widget.view.visualRect(widget.model.index(0, 0)).center())
    assert len(menus) == 1
    added = QSignalSpy(widget.playlist_add_requested)
    event = Drop(object(), track_ids_mime(track_ids), QPointF(5, 5))
    widget.view.dropEvent(event)
    assert not event.accepted and list(added) == []
