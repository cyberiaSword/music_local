"""
Определение путей приложения.
Работает и при запуске из исходников, и в собранном .exe.
"""
import os
import sys
from pathlib import Path


def get_app_dir() -> Path:
    """
    Папка, где лежит приложение:
    - при запуске из исходников: папка с main.py
    - при запуске .exe: папка с .exe (НЕ _internal/)
    """
    if getattr(sys, 'frozen', False):
        # sys.argv[0] — путь к запущенному .exe
        return Path(sys.argv[0]).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_data_dir() -> Path:
    """Папка data/ рядом с .exe или main.py."""
    d = get_app_dir() / 'data'
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_binaries_dir() -> Path:
    """
    Папка с внешними бинарниками (ffmpeg, deno).
    Они упакованы в _internal/binaries PyInstaller-ом.
    """
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / 'binaries'
    return get_app_dir() / 'binaries'


def get_assets_dir() -> Path:
    """
    Папка с assets (SVG-иконки).
    Они упакованы в _internal/assets PyInstaller-ом.
    """
    if getattr(sys, 'frozen', False):
        return Path(sys._MEIPASS) / 'assets'
    return get_app_dir() / 'assets'

def resource_path(relative_path):
    """Возвращает абсолютный путь к ресурсу, работает и в разработке, и в .exe"""
    if hasattr(sys, '_MEIPASS'):
        # После сборки PyInstaller ресурсы распакованы в sys._MEIPASS
        return os.path.join(sys._MEIPASS, relative_path)
    # В режиме разработки
    return os.path.join(os.path.abspath("."), relative_path)