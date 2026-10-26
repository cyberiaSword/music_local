"""Интеграция MainWindow: offscreen, временные данные, без native hooks и сети."""

import os
import socket
from unittest.mock import Mock

import pytest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
pytest.importorskip('PyQt6')
pytest.importorskip('PyQt6.QtMultimedia', reason='MainWindow использует реальный Player')
pytest.importorskip('pydantic', minversion='2', reason='Settings требует Pydantic 2')
pytest.importorskip('websockets.asyncio.server', reason='Импорт WebSocketServer в MainWindow')
pytest.importorskip('requests', reason='Импорт загрузчика обложек в MainWindow')
from PyQt6.QtCore import QCoreApplication, QEvent, QObject, QThread, Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtTest import QSignalSpy, QTest
from PyQt6.QtWidgets import QApplication, QDialog, QLineEdit, QSystemTrayIcon

from core import paths
from core.database import Database
from core.settings import Settings
from ui import main_window, overview_page, settings_dialog, track_list
from ui.controllers import lyrics_controller


class FakeHotkeys(QObject):
    play_pause = pyqtSignal()
    next_track = pyqtSignal()
    prev_track = pyqtSignal()
    stop_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.starts = 0
        self.stops = 0

    def start(self):
        self.starts += 1

    def stop(self):
        self.stops += 1


class FakeWebSocket(QObject):
    track_played = pyqtSignal(dict)
    client_connected = pyqtSignal(str)
    client_disconnected = pyqtSignal(str)

    def isRunning(self):
        return False


@pytest.fixture(scope='module')
def app():
    application = QApplication.instance() or QApplication([])
    previous = application.quitOnLastWindowClosed()
    application.setQuitOnLastWindowClosed(False)
    yield application
    application.setQuitOnLastWindowClosed(previous)


def flush():
    QApplication.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()


def focus(window, widget=None):
    window.showNormal()
    window.activateWindow()
    QApplication.processEvents()
    if QApplication.activeWindow() is not window:
        assert QTest.qWaitForWindowActive(window, 1000)
    target = widget if widget is not None else window.stack.currentWidget()
    target.setFocus(Qt.FocusReason.OtherFocusReason)
    QApplication.processEvents()
    assert QApplication.focusWidget() is target


def press(window, sequence):
    combination = QKeySequence(sequence)[0]
    target = QApplication.focusWidget() or window
    QTest.keyClick(target, combination.key(), combination.keyboardModifiers())
    QApplication.processEvents()


@pytest.fixture
def window_factory(app, monkeypatch, tmp_path):
    for module in (paths, main_window, overview_page, settings_dialog, track_list):
        monkeypatch.setattr(module, 'get_data_dir', lambda: tmp_path)
    monkeypatch.setattr(main_window, 'GlobalHotkeyManager', FakeHotkeys)
    monkeypatch.setattr(QSystemTrayIcon, 'isSystemTrayAvailable', lambda: False)
    monkeypatch.setattr(settings_dialog.SettingsDialog, '_refresh_cookies_status',
                        lambda self: None)
    forbidden = Mock(side_effect=AssertionError('Сеть в GUI-тесте запрещена'))
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr('requests.sessions.Session.request', forbidden)
    monkeypatch.setattr(lyrics_controller, 'fetch_lyrics', forbidden)
    windows = []

    def create(enabled=False):
        directory = tmp_path / str(len(windows))
        settings = Settings(directory / 'settings.json')
        settings.set('auto_download', False)
        settings.set('global_hotkeys_enabled', enabled)
        settings.save()
        window = main_window.MainWindow(Database(directory / 'tracks.db'), settings,
                                        FakeWebSocket())
        windows.append(window)
        monkeypatch.setattr(window.tray, 'show_message', Mock())
        focus(window)
        assert not window.download_manager.isRunning()
        assert window._environment_worker is None
        return window

    yield create
    for window in reversed(windows):
        window._shutdown()
        workers = window.findChildren(QThread)
        assert all(not worker.isRunning() for worker in workers)
        window.settings.set('minimize_to_tray', False)
        window.tray.hide()
        window.close()
        window.player._player.deleteLater()
        window.player._audio.deleteLater()
        window.player.deleteLater()
        window.deleteLater()
    flush()
    forbidden.assert_not_called()


@pytest.mark.parametrize('enabled', [False, True])
def test_initial_state_and_tray_persistence(window_factory, enabled):
    window = window_factory(enabled)
    manager = window.global_hotkeys
    assert (manager.starts, manager.stops) == (int(enabled), int(not enabled))
    assert window.tray.global_hotkeys_action.isChecked() is enabled
    assert window.local_shortcuts._installed
    assert len(window.findChildren(QShortcut)) == 15
    for state in (not enabled, enabled):
        before = (manager.starts, manager.stops)
        window.tray.global_hotkeys_action.trigger()
        assert window.tray.global_hotkeys_action.isChecked() is state
        assert Settings(window.settings.path).global_hotkeys_enabled is state
        assert (manager.starts, manager.stops) == (
            before[0] + int(state), before[1] + int(not state))


def test_local_navigation_sidebar_order(window_factory, monkeypatch):
    window = window_factory(False)
    assert window.sidebar.section_ids == ('overview', 'library', 'downloads', 'settings')
    shortcuts = window.local_shortcuts._shortcuts
    assert [shortcuts[f'page_{index}'].key().toString() for index in range(1, 5)] == [
        'Ctrl+1', 'Ctrl+2', 'Ctrl+3', 'Ctrl+4']
    assert 'page_5' not in shortcuts
    assert all(item.key() != QKeySequence('Ctrl+5')
               for item in window.findChildren(QShortcut))
    opened = Mock(return_value=QDialog.DialogCode.Rejected)
    monkeypatch.setattr(settings_dialog.SettingsDialog, 'exec', opened)
    for page in (3, 1, 2):
        focus(window)
        press(window, f'Ctrl+{page}')
        assert window.stack.currentIndex() == page - 1
        checked = window.sidebar._group.checkedButton()
        assert checked.property('section_id') == window.sidebar.section_ids[page - 1]
    focus(window)
    press(window, 'Ctrl+4')
    opened.assert_called_once()
    assert window.stack.currentIndex() == 1
    assert window.sidebar._group.checkedButton().property('section_id') == 'library'
    press(window, 'Ctrl+5')
    assert window.stack.currentIndex() == 1


@pytest.mark.parametrize('enabled', [False, True])
def test_dialog_immediate_and_modal_tray_sync(window_factory, monkeypatch, enabled):
    window = window_factory(enabled)
    receivers = window.receivers(window.global_hotkeys_changed)
    destroyed = []

    def execute(dialog):
        dialog.setModal(True)
        dialog.show()
        dialog.activateWindow()
        QApplication.processEvents()
        assert QApplication.activeModalWidget() is dialog
        destroyed.append(QSignalSpy(dialog.destroyed))
        toggled = QSignalSpy(dialog.global_hotkeys_toggled)
        checkbox = QSignalSpy(dialog.global_hotkeys_cb.toggled)
        assert dialog.global_hotkeys_cb.isChecked() is enabled
        before = (window.global_hotkeys.starts, window.global_hotkeys.stops)
        dialog.global_hotkeys_cb.click()
        assert list(toggled) == [[not enabled]]
        assert Settings(window.settings.path).global_hotkeys_enabled is not enabled
        assert window.tray.global_hotkeys_action.isChecked() is not enabled
        assert (window.global_hotkeys.starts, window.global_hotkeys.stops) == (
            before[0] + int(not enabled), before[1] + int(enabled))
        window.tray.global_hotkeys_action.trigger()
        assert dialog.global_hotkeys_cb.isChecked() is enabled
        assert list(toggled) == list(checkbox) == [[not enabled]]
        assert Settings(window.settings.path).global_hotkeys_enabled is enabled
        dialog.global_hotkeys_cb.click()
        dialog.reject()
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(settings_dialog.SettingsDialog, 'exec', execute)
    window._open_settings()
    assert window.receivers(window.global_hotkeys_changed) == receivers
    assert Settings(window.settings.path).global_hotkeys_enabled is not enabled
    flush()
    assert len(destroyed[0]) == 1
    changed = QSignalSpy(window.global_hotkeys_changed)
    before = (window.global_hotkeys.starts, window.global_hotkeys.stops)
    window.tray.global_hotkeys_action.trigger()
    assert list(changed) == [[enabled]]
    assert (window.global_hotkeys.starts, window.global_hotkeys.stops) == (
        before[0] + int(enabled), before[1] + int(not enabled))


def test_hide_keeps_global_transport_connected(window_factory, monkeypatch):
    window = window_factory(True)
    calls = {}
    for name in ('play_pause', 'next_track', 'prev_track', 'stop'):
        calls[name] = Mock()
        monkeypatch.setattr(window.player, name, calls[name])
    for sequence, name in [('Space', 'play_pause'), ('Ctrl+Right', 'next_track'),
                           ('Ctrl+Left', 'prev_track')]:
        press(window, sequence)
        calls[name].assert_called_once_with()
        calls[name].reset_mock()
    before = window.global_hotkeys.stops
    assert window.close() is False
    QApplication.processEvents()
    assert not window.isVisible()
    assert not window._shutdown_done
    assert window.global_hotkeys.stops == before
    assert window.local_shortcuts._installed
    for signal, name in [('play_pause', 'play_pause'), ('next_track', 'next_track'),
                         ('prev_track', 'prev_track'), ('stop_requested', 'stop')]:
        getattr(window.global_hotkeys, signal).emit()
        calls[name].assert_called_once_with()
    for shortcut in window.local_shortcuts._shortcuts.values():
        shortcut.activated.emit()
    assert all(callback.call_count == 1 for callback in calls.values())


@pytest.mark.parametrize('via_close', [False, True])
def test_shutdown_stops_global_and_local_once(window_factory, monkeypatch, via_close):
    window = window_factory(True)
    uninstall = Mock(wraps=window.local_shortcuts.uninstall)
    monkeypatch.setattr(window.local_shortcuts, 'uninstall', uninstall)
    shortcuts = tuple(window.findChildren(QShortcut))
    stops = window.global_hotkeys.stops
    if via_close:
        window.settings.set('minimize_to_tray', False)
        assert window.close()
    else:
        window._shutdown()
    assert window._shutdown_done
    assert window.global_hotkeys.stops == stops + 1
    assert not window.local_shortcuts._installed
    assert not window.local_shortcuts._shortcuts
    assert all(not shortcut.isEnabled() for shortcut in shortcuts)
    assert not window._stats_timer.isActive()
    window._shutdown()
    window._set_global_hotkeys_enabled(True)
    assert window.global_hotkeys.stops == stops + 1
    assert window.global_hotkeys.starts == 1
    uninstall.assert_called_once_with()


def test_search_focus_escape_and_editable_suppression(window_factory, monkeypatch):
    window = window_factory(False)
    transport = Mock()
    for name in ('play_pause', 'next_track', 'prev_track'):
        monkeypatch.setattr(window.player, name, getattr(transport, name))
    search = window.title_bar.search
    search.setText('alpha beta')
    focus(window)
    press(window, 'Ctrl+F')
    assert QApplication.focusWidget() is search
    assert search.selectedText() == 'alpha beta'
    search.deselect()
    press(window, 'Ctrl+F')
    assert search.selectedText() == 'alpha beta'
    search.setCursorPosition(len(search.text()))
    press(window, 'Space')
    assert search.text() == 'alpha beta '
    press(window, 'Esc')
    assert QApplication.focusWidget() is not search
    assert search.text() == 'alpha beta '
    press(window, 'Space')
    transport.play_pause.assert_called_once_with()
    transport.reset_mock()
    editor = QLineEdit(window)
    editor.show()
    focus(window, editor)
    volume = window.player.get_volume()
    index = window.stack.currentIndex()
    for sequence in ('Space', 'Ctrl+Right', 'Ctrl+Left', 'Ctrl+Up', 'Ctrl+Down',
                     'Ctrl+M', 'Ctrl+S', 'Ctrl+R', 'Ctrl+L', 'Ctrl+1', 'Ctrl+4'):
        press(window, sequence)
    assert editor.text() == ' '
    assert not transport.mock_calls
    assert window.player.get_volume() == volume
    assert window.stack.currentIndex() == index
    assert not window.player.is_shuffle()
    assert window.player.get_repeat_mode() == 'off'
    assert window.lyrics_panel.isHidden()
    for action, shortcut in window.local_shortcuts._shortcuts.items():
        assert shortcut.isEnabled() is (action in {'search', 'escape'})
        if action not in {'search', 'escape'}:
            shortcut.activated.emit()
    assert not transport.mock_calls
    press(window, 'Ctrl+F')
    assert QApplication.focusWidget() is search


@pytest.mark.parametrize('initial,sequence,expected', [
    (50, 'Ctrl+Up', 55), (50, 'Ctrl+Down', 45),
    (100, 'Ctrl+Up', 100), (0, 'Ctrl+Down', 0),
])
def test_volume_steps_and_clamps(window_factory, initial, sequence, expected):
    window = window_factory(False)
    window.player.set_volume(initial)
    changed = QSignalSpy(window.player.volume_changed)
    press(window, sequence)
    assert list(changed) == [[expected]]
    assert window.player.get_volume() == expected
    assert window.player_widget.volume.value() == expected


def test_mute_restore_and_volume_up_after_mute(window_factory):
    window = window_factory(False)
    player = window.player
    widget = window.player_widget
    player.set_volume(50)
    for expected in (0, 50):
        press(window, 'Ctrl+M')
        assert player.get_volume() == expected
        assert widget.volume.value() == expected
        assert widget._muted is (expected == 0)
    press(window, 'Ctrl+M')
    press(window, 'Ctrl+Up')
    assert player.get_volume() == widget.volume.value() == 5
    assert not widget._muted
    press(window, 'Ctrl+M')
    assert player.get_volume() == 0
    press(window, 'Ctrl+M')
    assert player.get_volume() == 5


def test_shuffle_repeat_and_lyrics_without_track(window_factory):
    window = window_factory(False)
    widget = window.player_widget
    for expected in (True, False):
        press(window, 'Ctrl+S')
        assert window.player.is_shuffle() is expected
        assert widget.btn_shuffle.isChecked() is expected
    assert window.player.get_repeat_mode() == 'off'
    for mode in ('all', 'one', 'off'):
        press(window, 'Ctrl+R')
        assert window.player.get_repeat_mode() == mode
        assert widget.btn_repeat.isChecked() is (mode != 'off')
    assert window.player.current_track() is None
    for visible in (True, False, True, False):
        press(window, 'Ctrl+L')
        assert window.lyrics_panel.isVisible() is visible
        assert widget.btn_lyrics.isChecked() is visible
        assert not window.lyrics_controller._workers

