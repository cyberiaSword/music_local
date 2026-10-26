"""Offscreen-проверки настроек горячих клавиш без native hooks."""

import os
import sys
from types import ModuleType

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
pytest.importorskip('PyQt6')
from PyQt6.QtCore import QCoreApplication, QEvent, Qt
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import (
    QApplication, QAbstractItemView, QCheckBox, QDialog, QPushButton, QTabWidget,
)

from core.settings import Settings
from ui.settings_dialog import SettingsDialog
from ui.tray import Tray


@pytest.fixture(scope='module')
def app():
    application = QApplication.instance() or QApplication([])
    yield application


@pytest.fixture
def dialog_factory(app, monkeypatch, tmp_path):
    monkeypatch.setattr(SettingsDialog, '_refresh_cookies_status', lambda self: None)
    dialogs = []

    def create(enabled=True):
        settings = Settings(tmp_path / f'settings-{len(dialogs)}.json')
        settings.set('global_hotkeys_enabled', enabled)
        settings.save()
        dialog = SettingsDialog(settings, tmp_path)
        dialogs.append(dialog)
        return dialog

    yield create
    for dialog in dialogs:
        dialog.close()
        dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def button(dialog, text):
    return next(item for item in dialog.findChildren(QPushButton)
                if item.text() == text)


def table_rows(dialog):
    table = dialog.hotkeys_table
    return [tuple(table.item(row, col).text() for col in range(table.columnCount()))
            for row in range(table.rowCount())]


@pytest.mark.parametrize('enabled', [True, False])
def test_checkbox_initial_state_and_silent_sync(dialog_factory, enabled):
    dialog = dialog_factory(enabled)
    assert dialog.global_hotkeys_cb.text() == 'Включить глобальные клавиши'
    assert dialog.global_hotkeys_cb.isChecked() is enabled
    spy = QSignalSpy(dialog.global_hotkeys_toggled)
    checkbox_spy = QSignalSpy(dialog.global_hotkeys_cb.toggled)
    for state in [not enabled, enabled, enabled]:
        dialog.set_global_hotkeys_enabled(state)
        assert dialog.global_hotkeys_cb.isChecked() is state
    assert len(spy) == len(checkbox_spy) == 0
    dialog.global_hotkeys_cb.click()
    assert list(spy) == [[not enabled]]
    # Без MainWindow диалог только сообщает об изменении, не сохраняет сам.
    assert dialog.settings.global_hotkeys_enabled is enabled


def test_cancel_does_not_undo_immediate_setting(dialog_factory):
    dialog = dialog_factory()
    settings = dialog.settings
    changed = QSignalSpy(dialog.settings_changed)

    def persist(enabled):
        settings.set('global_hotkeys_enabled', enabled)
        settings.save()

    dialog.global_hotkeys_toggled.connect(persist)
    dialog.auto_download_cb.setChecked(False)
    dialog.global_hotkeys_cb.click()
    assert Settings(settings.path).global_hotkeys_enabled is False
    button(dialog, 'Отмена').click()
    assert dialog.result() == QDialog.DialogCode.Rejected
    assert Settings(settings.path).global_hotkeys_enabled is False
    assert settings.get('auto_download') is True
    assert len(changed) == 0


@pytest.mark.parametrize('enabled', [True, False])
def test_save_persists_checkbox_without_feedback(dialog_factory, enabled):
    dialog = dialog_factory(not enabled)
    dialog.set_global_hotkeys_enabled(enabled)
    toggled = QSignalSpy(dialog.global_hotkeys_toggled)
    changed = QSignalSpy(dialog.settings_changed)
    button(dialog, 'Сохранить').click()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert Settings(dialog.settings.path).global_hotkeys_enabled is enabled
    assert len(toggled) == 0
    assert len(changed) == 1


def test_readonly_list_and_four_navigation_pages(dialog_factory):
    dialog = dialog_factory()
    tabs = dialog.findChild(QTabWidget)
    page = next(tabs.widget(index) for index in range(tabs.count())
                if tabs.tabText(index) == 'Горячие клавиши')
    assert page.findChildren(QCheckBox) == [dialog.global_hotkeys_cb]
    table = dialog.hotkeys_table
    assert table.editTriggers() == QAbstractItemView.EditTrigger.NoEditTriggers
    for row in range(table.rowCount()):
        for column in range(table.columnCount()):
            assert not table.item(row, column).flags() & Qt.ItemFlag.ItemIsEditable
    rows = table_rows(dialog)
    assert [sequence for scope, sequence, _ in rows if scope == 'Глобальные'] == [
        'Media Play/Pause', 'Media Next', 'Media Previous', 'Media Stop',
        'Ctrl+Alt+Space',
    ]
    navigation = [(sequence, label) for scope, sequence, label in rows
                  if scope == 'В окне' and sequence in
                  ('Ctrl+1', 'Ctrl+2', 'Ctrl+3', 'Ctrl+4', 'Ctrl+5')]
    assert [sequence for sequence, _ in navigation] == [
        'Ctrl+1', 'Ctrl+2', 'Ctrl+3', 'Ctrl+4',
    ]


def test_list_uses_imported_bindings(dialog_factory, monkeypatch):
    module = ModuleType('ui.shortcuts')
    module.BINDINGS = (
        ('custom', 'Ctrl+Shift+K', 'Команда из общего реестра'),
    )
    monkeypatch.setitem(sys.modules, 'ui.shortcuts', module)
    imported = dialog_factory()
    local_rows = [row for row in table_rows(imported) if row[0] == 'В окне']
    assert local_rows == [('В окне', 'Ctrl+Shift+K', 'Команда из общего реестра')]


def test_tray_sync_and_bidirectional_signals(app, dialog_factory):
    dialog = dialog_factory(False)
    tray = Tray()
    try:
        assert tray.global_hotkeys_action.isCheckable()
        assert tray.global_hotkeys_action.text() == 'Глобальные клавиши'
        tray_spy = QSignalSpy(tray.global_hotkeys_toggled)
        action_spy = QSignalSpy(tray.global_hotkeys_action.toggled)
        dialog_spy = QSignalSpy(dialog.global_hotkeys_toggled)
        tray.set_global_hotkeys_enabled(False)
        assert not tray.global_hotkeys_action.isChecked()
        assert len(tray_spy) == len(action_spy) == 0

        def apply(enabled):
            dialog.settings.global_hotkeys_enabled = enabled
            dialog.settings.save()
            dialog.set_global_hotkeys_enabled(enabled)
            tray.set_global_hotkeys_enabled(enabled)

        dialog.global_hotkeys_toggled.connect(apply)
        tray.global_hotkeys_toggled.connect(apply)
        tray.global_hotkeys_action.trigger()
        assert list(tray_spy) == [[True]]
        assert len(dialog_spy) == 0
        assert dialog.global_hotkeys_cb.isChecked()
        dialog.global_hotkeys_cb.click()
        assert list(dialog_spy) == [[False]]
        assert list(tray_spy) == [[True]]
        assert not tray.global_hotkeys_action.isChecked()
        assert Settings(dialog.settings.path).global_hotkeys_enabled is False
        # Синхронизация идёт по desired settings, а не состоянию native listener.
        apply(True)
        assert dialog.global_hotkeys_cb.isChecked()
        assert tray.global_hotkeys_action.isChecked()
        assert list(tray_spy) == [[True]]
        assert list(dialog_spy) == [[False]]
    finally:
        tray.hide()
        tray.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
