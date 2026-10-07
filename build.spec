# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec для YT Music Local.
Сборка: pyinstaller build.spec --noconfirm
"""

from pathlib import Path

# Корень проекта
PROJECT_DIR = Path(SPECPATH).resolve()

# ============================================================
# DATAS — что упаковать как ресурсы (не код)
# ============================================================
datas = []

# Assets (SVG-иконки, app.ico)
assets_dir = PROJECT_DIR / 'assets'
if assets_dir.exists():
    datas.append((str(assets_dir), 'assets'))

# ============================================================
# BINARIES — внешние .exe (ffmpeg, deno)
# ============================================================
binaries = []
binaries_dir = PROJECT_DIR / 'binaries'
if binaries_dir.exists():
    for f in binaries_dir.iterdir():
        if f.is_file():
            binaries.append((str(f), 'binaries'))

# ============================================================
# HIDDENIMPORTS — модули, которые PyInstaller не видит
# ============================================================
hiddenimports = [
    # ---- yt-dlp ----
    'yt_dlp',
    'yt_dlp.extractor.youtube',
    'yt_dlp.extractor.youtube.jsc',
    'yt_dlp.extractor.youtube.jsc._builtin',
    'yt_dlp.extractor.youtube.jsc._builtin.ejs',
    'yt_dlp.downloader',
    'yt_dlp.downloader.http',
    'yt_dlp.downloader.external',
    'yt_dlp.postprocessor',
    'yt_dlp.postprocessor.ffmpeg',
    'yt_dlp.networking',
    'yt_dlp.networking._urllib',
    'yt_dlp.networking._requests',
    'yt_dlp.utils',
    'yt_dlp.utils._utils',
    'yt_dlp.compat',
    'yt_dlp.compat._legacy',
    'yt_dlp.compat._deprecated',
    'yt_dlp.utils._legacy',
    'yt_dlp.utils._deprecated',
    'yt_dlp_ejs',
    'yt_dlp_ejs.yt',

    # ---- Опциональные для yt-dlp ----
    'mutagen',
    'brotli',
    'Cryptodome',
    'Crypto',
    'certifi',
    'requests',
    'urllib3',

    # ---- Наши библиотеки ----
    'lyriq',
    'websockets',
    'websockets.asyncio',
    'websockets.asyncio.server',
    'websockets.server',

    # ---- PyQt6 ----
    'PyQt6.QtSvg',
    'PyQt6.QtMultimedia',
    'PyQt6.QtNetwork',
    'PyQt6.QtWidgets',
    'PyQt6.QtCore',
    'PyQt6.QtGui',

    # ---- Наши модули core ----
    'core.database',
    'core.settings',
    'core.paths',
    'core.ws_server',
    'core.player',
    'core.downloader',
    'core.download_manager',
    'core.covers',
    'core.lyrics',
    'core.optimizer',

    # ---- Наши модули ui ----
    'ui.main_window',
    'ui.sidebar',
    'ui.track_list',
    'ui.player',
    'ui.downloads_page',
    'ui.lyrics_panel',
    'ui.settings_dialog',
    'ui.tray',
    'ui.title_bar',
    'ui.styles',
    'ui.icons',
    'ui.status_icons',
    'ui.widgets',
    'ui.optimizer_worker',
]

# ============================================================
# EXCLUDES — что не включать (уменьшает размер .exe)
# ============================================================
excludes = [
    'tkinter',
    'matplotlib',
    'numpy',
    'scipy',
    'pandas',
    'PIL.ImageQt',
]

# ============================================================
# ANALYSIS
# ============================================================
a = Analysis(
    ['main.py'],
    pathex=[str(PROJECT_DIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

# ============================================================
# PYZ — сжатый Python-код
# ============================================================
pyz = PYZ(a.pure)

# ============================================================
# EXE — сам исполняемый файл
# ============================================================
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='YTMusicLocal',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # ← True для отладки, потом поменяйте на False
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PROJECT_DIR / 'assets' / 'app.ico') if (PROJECT_DIR / 'assets' / 'app.ico').exists() else None,
)

# ============================================================
# COLLECT — папка dist/YTMusicLocal/
# ============================================================
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='YTMusicLocal',
)