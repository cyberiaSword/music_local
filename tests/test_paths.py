"""
Тесты для core.paths.

Проверяем, что пути определяются правильно
и при запуске из исходников, и в собранном .exe.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from core.paths import get_app_dir, get_data_dir, get_binaries_dir, get_assets_dir


class TestGetAppDir:
    """Тесты для get_app_dir()."""

    def test_not_frozen(self):
        """При запуске из исходников возвращает корень проекта."""
        with patch.object(sys, 'frozen', False, create=True):
            result = get_app_dir()
            # Должна быть папка, содержащая main.py или core/
            assert result.exists()
            assert (result / 'core').exists() or (result / 'main.py').exists()

    def test_frozen(self, tmp_path):
        """При запуске из .exe возвращает папку с .exe."""
        fake_exe = tmp_path / 'YTMusicLocal.exe'
        fake_exe.touch()

        with patch.object(sys, 'frozen', True, create=True):
            with patch.object(sys, 'argv', [str(fake_exe)]):
                result = get_app_dir()
                assert result == tmp_path


class TestGetDataDir:
    """Тесты для get_data_dir()."""

    def test_creates_dir(self, tmp_path):
        """Создаёт data/, если её нет."""
        with patch.object(sys, 'frozen', True, create=True):
            with patch.object(sys, 'argv', [str(tmp_path / 'app.exe')]):
                result = get_data_dir()
                assert result.exists()
                assert result.name == 'data'
                assert result.parent == tmp_path

    def test_returns_existing(self, tmp_path):
        """Возвращает существующую data/."""
        data = tmp_path / 'data'
        data.mkdir()

        with patch.object(sys, 'frozen', True, create=True):
            with patch.object(sys, 'argv', [str(tmp_path / 'app.exe')]):
                result = get_data_dir()
                assert result == data


class TestGetBinariesDir:
    """Тесты для get_binaries_dir()."""

    def test_not_frozen(self):
        """Из исходников — папка binaries/ рядом с проектом."""
        with patch.object(sys, 'frozen', False, create=True):
            result = get_binaries_dir()
            assert result.name == 'binaries'

    def test_frozen(self, tmp_path):
        """Из .exe — _MEIPASS/binaries."""
        with patch.object(sys, 'frozen', True, create=True):
            with patch.object(sys, '_MEIPASS', str(tmp_path), create=True):
                result = get_binaries_dir()
                assert result == tmp_path / 'binaries'


class TestGetAssetsDir:
    """Тесты для get_assets_dir()."""

    def test_not_frozen(self):
        """Из исходников — папка assets/."""
        with patch.object(sys, 'frozen', False, create=True):
            result = get_assets_dir()
            assert result.name == 'assets'

    def test_frozen(self, tmp_path):
        """Из .exe — _MEIPASS/assets."""
        with patch.object(sys, 'frozen', True, create=True):
            with patch.object(sys, '_MEIPASS', str(tmp_path), create=True):
                result = get_assets_dir()
                assert result == tmp_path / 'assets'