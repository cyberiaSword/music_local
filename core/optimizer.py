"""
Оптимизатор библиотеки MP3.
Перекодирует файлы с битрейтом > 250 kbps в V0 (~245 kbps VBR).
"""

import json
import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

logger = logging.getLogger('yt-local.optimizer')


@dataclass
class OptimizeResult:
    """Результат обработки одного файла."""
    path: Path
    old_size: int
    new_size: int
    old_bitrate: int
    action: str          # 'optimized' | 'skipped' | 'failed'
    message: str = ''


def _ffprobe_bitrate(path: Path) -> int | None:
    """Возвращает битрейт аудио в kbps или None при ошибке."""
    try:
        result = subprocess.run(
            [
                'ffprobe', '-v', 'error',
                '-select_streams', 'a:0',
                '-show_entries', 'stream=bit_rate',
                '-of', 'json',
                str(path)
            ],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        streams = data.get('streams', [])
        if not streams:
            return None
        bitrate = streams[0].get('bit_rate')
        if bitrate is None:
            return None
        return int(bitrate) // 1000
    except Exception as e:
        logger.warning(f"ffprobe ошибка для {path.name}: {e}")
        return None


def _transcode_to_v0(src: Path, dst: Path) -> bool:
    """Перекодирует MP3 в V0 (LAME -V0)."""
    try:
        result = subprocess.run(
            [
                'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                '-i', str(src),
                '-codec:a', 'libmp3lame',
                '-q:a', '0',
                '-map_metadata', '0',
                '-id3v2_version', '3',
                str(dst)
            ],
            capture_output=True, text=True, timeout=600
        )
        if result.returncode != 0:
            logger.error(f"ffmpeg ошибка: {result.stderr.strip()}")
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.error(f"ffmpeg таймаут для {src.name}")
        return False
    except Exception as e:
        logger.error(f"ffmpeg исключение: {e}")
        return False


def optimize_file(
    path: Path,
    threshold_kbps: int = 250,
    dry_run: bool = False
) -> OptimizeResult:
    """Обрабатывает один MP3-файл."""
    if not path.exists() or path.suffix.lower() != '.mp3':
        return OptimizeResult(path, 0, 0, 0, 'skipped', 'не MP3')

    old_size = path.stat().st_size
    bitrate = _ffprobe_bitrate(path)

    if bitrate is None:
        return OptimizeResult(path, old_size, old_size, 0, 'failed', 'нет данных о битрейте')

    if bitrate <= threshold_kbps:
        return OptimizeResult(
            path, old_size, old_size, bitrate, 'skipped',
            f'{bitrate} kbps ≤ {threshold_kbps} kbps'
        )

    if dry_run:
        return OptimizeResult(
            path, old_size, 0, bitrate, 'optimized',
            f'[DRY RUN] будет сжат: {bitrate} kbps'
        )

    tmp = path.with_suffix('.tmp.mp3')

    if not _transcode_to_v0(path, tmp):
        if tmp.exists():
            tmp.unlink()
        return OptimizeResult(path, old_size, old_size, bitrate, 'failed', 'ошибка ffmpeg')

    new_size = tmp.stat().st_size

    if new_size >= old_size:
        tmp.unlink()
        return OptimizeResult(
            path, old_size, old_size, bitrate, 'skipped',
            'сжатие не дало выигрыша'
        )

    try:
        backup = path.with_suffix('.mp3.bak')
        path.rename(backup)
        tmp.rename(path)
        backup.unlink()
    except Exception as e:
        logger.error(f"Ошибка замены {path.name}: {e}")
        if tmp.exists():
            tmp.unlink()
        return OptimizeResult(path, old_size, old_size, bitrate, 'failed', f'ошибка замены: {e}')

    saved = old_size - new_size
    saved_pct = saved / old_size * 100
    logger.info(
        f"Оптимизирован {path.name}: "
        f"{bitrate} kbps → V0, "
        f"{old_size/1024/1024:.1f} МБ → {new_size/1024/1024:.1f} МБ "
        f"(-{saved_pct:.0f}%)"
    )
    return OptimizeResult(
        path, old_size, new_size, bitrate, 'optimized',
        f'{bitrate} kbps → V0, -{saved_pct:.0f}%'
    )


def optimize_library(
    downloads_dir: Path,
    threshold_kbps: int = 250,
    dry_run: bool = False,
    progress_callback: Callable[[int, int, OptimizeResult], None] | None = None,
    stop_flag: Callable[[], bool] | None = None,
) -> list[OptimizeResult]:
    """Обходит всю папку downloads и оптимизирует MP3."""
    files = sorted(downloads_dir.rglob('*.mp3'))
    total = len(files)
    results: list[OptimizeResult] = []

    logger.info(f"Начинаю оптимизацию: {total} файлов, dry_run={dry_run}")

    for i, path in enumerate(files, start=1):
        if stop_flag and stop_flag():
            logger.info("Оптимизация прервана пользователем")
            break

        result = optimize_file(path, threshold_kbps, dry_run)
        results.append(result)

        if progress_callback:
            progress_callback(i, total, result)

    optimized = sum(1 for r in results if r.action == 'optimized')
    skipped = sum(1 for r in results if r.action == 'skipped')
    failed = sum(1 for r in results if r.action == 'failed')
    saved_bytes = sum(r.old_size - r.new_size for r in results if r.action == 'optimized')

    logger.info(
        f"Оптимизация завершена: "
        f"сжато {optimized}, пропущено {skipped}, ошибок {failed}. "
        f"Освобождено {saved_bytes/1024/1024:.1f} МБ"
    )
    return results