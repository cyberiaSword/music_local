"""
Общие фикстуры pytest.

Фикстуры — это функции, которые подготавливают данные для тестов.
pytest автоматически подставляет их, если имя совпадает с аргументом.
"""

import shutil
import sys
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def tmp_data_dir():
    """
    Создаёт временную папку data/, удаляет после теста.
    Используется для тестов, работающих с файлами.
    """
    tmp = Path(tempfile.mkdtemp(prefix='yml_test_'))
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def tmp_db_path(tmp_data_dir):
    """Путь к временной БД."""
    return tmp_data_dir / 'tracks.db'


@pytest.fixture
def tmp_settings_path(tmp_data_dir):
    """Путь к временному settings.json."""
    return tmp_data_dir / 'settings.json'


@pytest.fixture(autouse=True)
def reset_sys_argv():
    """
    Сохраняет и восстанавливает sys.argv между тестами.
    Нужно, чтобы тесты paths.py не портили argv других тестов.
    """
    original = sys.argv.copy()
    yield
    sys.argv = original