"""MainWindow: плейлисты/очередь без сети, native hotkeys и запуска декодера."""

from unittest.mock import Mock

import pytest

from .test_hotkey_integration import app, window_factory  # noqa: F401
from .test_playlist_ui import choose_menu, ids, populate, settled, wait_for

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QApplication, QInputDialog, QMessageBox, QPushButton

from core.database import Database
from core.settings import Settings
from ui import main_window
from ui.overview_page import OverviewTrackCard


def selected_id(window):
    item = window.sidebar._playlists.currentItem()
    return item.data(Qt.ItemDataRole.UserRole) if item else None


def create_from_button(window, monkeypatch, name='  New mix  ', accepted=True):
    dialog = Mock(return_value=(name, accepted))
    monkeypatch.setattr(QInputDialog, 'getText', dialog)
    next(button for button in window.sidebar.findChildren(QPushButton)
         if button.text() == '+ Создать плейлист').click()
    dialog.assert_called_once()


def test_create_rename_delete_cancel_confirm_preserves_tracks(
        app, window_factory, monkeypatch):
    window = window_factory()
    _, track_ids = populate(window.db)
    create_from_button(window, monkeypatch, accepted=False)
    assert len(window.db.list_playlists()) == 1
    create_from_button(window, monkeypatch)
    playlist_id = window._active_playlist_id
    assert playlist_id is not None
    assert selected_id(window) == playlist_id
    assert window.stack.currentWidget() is window.track_list
    assert window.track_list.title.text() == 'New mix'
    window.sidebar.playlist_tracks_dropped.emit(playlist_id, track_ids)
    settled(app, window.track_list)
    assert ids(window.track_list) == track_ids
    before = window.db.get_playlist_tracks(playlist_id)
    monkeypatch.setattr(QInputDialog, 'getText', Mock(return_value=('Ignored', False)))
    window.sidebar.playlist_rename_requested.emit(playlist_id)
    assert window.track_list.title.text() == 'New mix'
    rename = Mock(return_value=('  Renamed  ', True))
    monkeypatch.setattr(QInputDialog, 'getText', rename)
    window.sidebar.playlist_rename_requested.emit(playlist_id)
    assert rename.call_args.kwargs['text'] == 'New mix'
    assert window.track_list.title.text() == 'Renamed'
    assert selected_id(window) == playlist_id
    assert window.db.get_playlist_tracks(playlist_id) == before
    question = Mock(return_value=QMessageBox.StandardButton.No)
    monkeypatch.setattr(QMessageBox, 'question', question)
    window.sidebar.playlist_delete_requested.emit(playlist_id)
    assert question.call_args.args[-1] == QMessageBox.StandardButton.No
    assert selected_id(window) == playlist_id
    assert window.db.get_playlist_tracks(playlist_id) == before
    question.return_value = QMessageBox.StandardButton.Yes
    window.sidebar.playlist_delete_requested.emit(playlist_id)
    settled(app, window.track_list)
    assert all(item.id != playlist_id for item in window.db.list_playlists())
    assert window.db.get_playlist_tracks(playlist_id) == []
    assert all(window.db.get_track(track_id) is not None for track_id in track_ids)
    assert window._active_playlist_id is None
    assert window.track_list._playlist_id is None
    assert window.sidebar._group.checkedButton().property('section_id') == 'library'


@pytest.mark.parametrize('operation', ['create', 'rename'])
def test_blank_name_reports_error_without_mutation(window_factory, monkeypatch, operation):
    window = window_factory()
    playlist_id, _ = populate(window.db)
    window._refresh_playlists()
    before = window.db.list_playlists()
    error = Mock()
    monkeypatch.setattr(window.toast, 'show_message', error)
    monkeypatch.setattr(QInputDialog, 'getText', Mock(return_value=(' \t ', True)))
    if operation == 'create':
        window.sidebar.playlist_create_requested.emit()
    else:
        window.sidebar.playlist_rename_requested.emit(playlist_id)
    assert window.db.list_playlists() == before
    error.assert_called_once()


def test_selection_settings_library_and_global_search(app, window_factory, monkeypatch):
    window = window_factory()
    playlist_id, track_ids = populate(window.db)
    window._refresh_playlists()
    window.sidebar._playlists.setCurrentRow(0)
    settled(app, window.track_list)
    assert window._active_playlist_id == selected_id(window) == playlist_id
    assert window.stack.currentIndex() == 1
    assert ids(window.track_list) == track_ids
    opened = Mock()
    monkeypatch.setattr(window, '_open_settings', opened)
    window.sidebar._group.buttons()[3].click()
    opened.assert_called_once_with()
    assert window._active_playlist_id == selected_id(window) == playlist_id
    assert window.stack.currentIndex() == 1
    window.sidebar._group.buttons()[1].click()
    settled(app, window.track_list)
    assert window._active_playlist_id is None and selected_id(window) is None
    assert window.track_list.sort_combo.isEnabled()
    window.sidebar.playlist_selected.emit(playlist_id)
    window.title_bar.search.setText('Track 001')
    settled(app, window.track_list)
    assert window._active_playlist_id is None and selected_id(window) is None
    assert window.track_list._playlist_id is None
    assert window.stack.currentIndex() == 1
    assert window.sidebar._group.buttons()[1].isChecked()
    assert ids(window.track_list) == track_ids[1:2]


@pytest.mark.parametrize('search', ['', 'Track 00'])
def test_playlist_playback_uses_full_db_order_not_loaded_subset(
        app, window_factory, monkeypatch, search):
    window = window_factory()
    playlist_id, track_ids = populate(window.db, 107)
    window.db.reorder_playlist(playlist_id, track_ids[::-1])
    window._refresh_playlists()
    window.sidebar.playlist_selected.emit(playlist_id)
    if search:
        window.track_list.set_external_search(search)
    settled(app, window.track_list)
    loaded_ids = ids(window.track_list)
    assert 0 < len(loaded_ids) < len(track_ids)
    play = Mock(return_value=True)
    monkeypatch.setattr(window.player, 'play_track', play)
    index = window.track_list.model.index(3, 0)
    chosen = index.data(Qt.ItemDataRole.UserRole)
    window.track_list.view.doubleClicked.emit(index)
    play.assert_called_once()
    assert play.call_args.args == (chosen,)
    assert [track.id for track in play.call_args.kwargs['queue']] == track_ids[::-1]
    assert chosen.id == loaded_ids[3]


def test_playlist_add_remove_reorder_signal_wiring(app, window_factory):
    window = window_factory()
    playlist_id, track_ids = populate(window.db, 4)
    target_id = window.db.create_playlist('Target')
    window._refresh_playlists()
    window.sidebar.playlist_tracks_dropped.emit(target_id, track_ids[:3])
    window.sidebar.playlist_selected.emit(target_id)
    settled(app, window.track_list)
    assert ids(window.track_list) == track_ids[:3]
    window.track_list.playlist_add_requested.emit(target_id, track_ids[3])
    settled(app, window.track_list)
    assert ids(window.track_list) == track_ids
    window.track_list.playlist_reorder_requested.emit(target_id, track_ids[::-1])
    settled(app, window.track_list)
    assert ids(window.track_list) == track_ids[::-1]
    window.track_list.playlist_remove_requested.emit(target_id, track_ids[1])
    settled(app, window.track_list)
    assert ids(window.track_list) == [track_ids[3], track_ids[2], track_ids[0]]
    assert [track.id for track in window.db.get_playlist_tracks(playlist_id)] == track_ids
    assert all(window.db.get_track(track_id) is not None for track_id in track_ids)


def menu_target(app, window, source):
    if source == 'overview':
        page = window.overview_page
        page.refresh()
        wait_for(app, lambda: page._worker is None and not page._pending)
        window.stack.setCurrentWidget(page)
        app.processEvents()
        card = next(page._recent_layout.itemAt(index).widget()
                    for index in range(page._recent_layout.count())
                    if isinstance(page._recent_layout.itemAt(index).widget(), OverviewTrackCard))
        return page, card, QPoint(5, 5), card.track.id
    if source == 'downloads':
        page = window.downloads_page
        page.refresh()
        settled(app, page)
        window.stack.setCurrentWidget(page)
        app.processEvents()
        index = page.table.model().index(1, 0)
        return (page, page, page.table.visualRect(index).center(),
                page.table.item(1, 0).data(Qt.ItemDataRole.UserRole))
    page = window.track_list if source == 'library' else window.queue_panel
    if source == 'library':
        window.track_list.refresh()
        window.stack.setCurrentWidget(page)
        settled(app, page)
    else:
        window.player_widget.btn_queue.setChecked(True)
    app.processEvents()
    page.view.doItemsLayout()
    index = page.model.index(2 if source == 'queue' else 1, 0)
    return page, page, page.view.visualRect(index).center(), index.data(Qt.ItemDataRole.UserRole).id


@pytest.mark.parametrize('source', ['library', 'queue', 'overview', 'downloads'])
@pytest.mark.parametrize('label,position', [
    ('Играть следующим', 'next'), ('Добавить в очередь', 'end'), ('Destination', None),
])
def test_actual_page_menus_forward_signals_to_queue_and_db(
        app, window_factory, monkeypatch, source, label, position):
    window = window_factory()
    _, track_ids = populate(window.db)
    target_id = window.db.create_playlist('Destination')
    window._refresh_playlists()
    window.player.set_queue([window.db.get_track(track_id) for track_id in track_ids], 0)
    page, menu_owner, point, track_id = menu_target(app, window, source)
    before = window.player_controller.queue_ids
    move_next = source == 'queue' and position == 'next'
    signal = (page.next_requested if move_next else page.enqueue_requested) if position else (
        page.playlist_add_requested)
    received = QSignalSpy(signal)
    choose_menu(monkeypatch, label)
    menu_owner._show_context_menu(point)
    if position:
        expected = list(before)
        if move_next:
            row = before.index(track_id)
            assert list(received) == [[row]]
            expected.insert(1, expected.pop(row))
        else:
            assert list(received) == [[track_id, position]]
            expected.insert(1 if position == 'next' else len(expected), track_id)
        assert window.player_controller.queue_ids == expected
        assert window.queue_panel.model.rowCount() == len(expected)
        assert window.track_list.model.is_queued(track_id)
        assert Settings(window.settings.path).get('queue_track_ids') == expected
        assert window.db.get_playlist_tracks(target_id) == []
    else:
        assert list(received) == [[target_id, track_id]]
        assert [track.id for track in window.db.get_playlist_tracks(target_id)] == [track_id]
        assert window.player_controller.queue_ids == before


def test_queue_button_restore_and_play_transport(app, window_factory, monkeypatch, tmp_path):
    directory = tmp_path / '0'
    db = Database(directory / 'tracks.db')
    _, track_ids = populate(db)
    settings = Settings(directory / 'settings.json')
    settings.set('queue_track_ids', [track_ids[0], 999999, track_ids[1], track_ids[0]])
    settings.set('queue_current_index', 2)
    settings.save()
    window = window_factory()
    expected = [track_ids[0], track_ids[1], track_ids[0]]
    settled(app, window.track_list)
    assert window.player_controller.queue_ids == expected
    assert window.player_controller.current_index == 1
    assert window.player.current_track() is None
    assert window.queue_panel.model.rowCount() == 3
    assert not any(window.queue_panel.model.item(row).font().bold() for row in range(3))
    assert [window.track_list.model.is_queued(track_id) for track_id in track_ids] == [True, True, False]
    assert Settings(window.settings.path).get('queue_track_ids') == expected
    assert Settings(window.settings.path).get('queue_current_index') == 1
    toggled = QSignalSpy(window.player_widget.queue_toggled)
    assert not window.queue_panel.isVisible()
    window.player_widget.btn_queue.click()
    assert window.queue_panel.isVisible()
    window.player_widget.btn_queue.click()
    assert not window.queue_panel.isVisible()
    assert list(toggled) == [[True], [False]]
    play = Mock(return_value=True)
    monkeypatch.setattr(window.player, 'play_queue_index', play)
    window.player_widget.btn_play.click()
    play.assert_called_once_with(1)
    play.reset_mock()
    next(action for action in window.tray.contextMenu().actions()
         if action.text() == 'Играть / Пауза').trigger()
    play.assert_called_once_with(1)
    window.queue_panel.clear_button.click()
    assert window.player_controller.queue_ids == []
    assert window.queue_panel.placeholder.isVisible() is False
    window.player_widget.btn_queue.click()
    assert window.queue_panel.placeholder.isVisible()
    assert not any(window.track_list.model.is_queued(track_id) for track_id in track_ids)
    assert Settings(window.settings.path).get('queue_track_ids') == []


def test_player_transport_and_tray_menu_wiring(app, window_factory, monkeypatch):
    calls = []
    monkeypatch.setattr(main_window.Player, 'next_track', lambda self: calls.append('next'))
    monkeypatch.setattr(main_window.Player, 'prev_track', lambda self: calls.append('prev'))
    monkeypatch.setattr(main_window.Player, 'play_pause', lambda self: calls.append('play'))
    window = window_factory()
    window.player_widget.btn_next.click()
    window.player_widget.btn_prev.click()
    window.player_widget.btn_play.click()
    assert calls == ['next', 'prev', 'play']
    actions = {action.text(): action for action in window.tray.contextMenu().actions()}
    spies = {name: QSignalSpy(getattr(window.tray, name)) for name in (
        'next_requested', 'prev_requested', 'play_pause_requested', 'show_window_requested',
        'quit_requested')}
    for label in ('Следующий', 'Предыдущий', 'Играть / Пауза'):
        actions[label].trigger()
    assert calls == ['next', 'prev', 'play'] * 2
    window.hide()
    actions['Развернуть'].trigger()
    app.processEvents()
    assert window.isVisible() and not window.isMinimized()
    quit_app = Mock()
    monkeypatch.setattr(QApplication, 'quit', quit_app)
    actions['Выход'].trigger()
    assert window._shutdown_done
    quit_app.assert_called_once_with()
    assert all(len(spy) == 1 for spy in spies.values())


def test_queue_panel_play_move_remove_and_highlight_wiring(
        app, window_factory, monkeypatch):
    window = window_factory()
    _, track_ids = populate(window.db)
    tracks = [window.db.get_track(track_id) for track_id in track_ids]
    window.player.set_queue([tracks[0], tracks[1], tracks[0], tracks[2]], 2)
    window.player_widget.btn_queue.click()
    panel = window.queue_panel
    app.processEvents()
    played = QSignalSpy(panel.play_requested)
    play = Mock(return_value=True)
    monkeypatch.setattr(window.player, 'play_queue_index', play)
    panel.view.doubleClicked.emit(panel.model.index(2, 0))
    assert list(played) == [[2]]
    play.assert_called_once_with(2)
    moved = QSignalSpy(panel.move_requested)
    panel.view.move_requested.emit(2, 0)
    assert list(moved) == [[2, 0]]
    assert window.player_controller.queue_ids == [track_ids[0], track_ids[0], track_ids[1], track_ids[2]]
    assert window.player_controller.current_index == 0
    removed = QSignalSpy(panel.remove_requested)
    choose_menu(monkeypatch, 'Удалить')
    panel.view.doItemsLayout()
    point = panel.view.visualRect(panel.model.index(1, 0)).center()
    panel.view.customContextMenuRequested.emit(point)
    assert list(removed) == [[1]]
    assert window.player_controller.queue_ids == track_ids
    assert window.player_controller.current_index == 0
    assert panel.model.rowCount() == 3
    assert not any(panel.model.item(row).font().bold() for row in range(3))
    window.player_controller.queue_changed.emit(tracks, 1)
    assert [panel.model.item(row).font().bold() for row in range(3)] == [False, True, False]
    assert all(window.track_list.model.is_queued(track_id) for track_id in track_ids)
