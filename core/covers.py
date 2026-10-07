"""
Работа с обложками: постер YouTube + кадр из видео.
"""

import logging
import subprocess
from pathlib import Path

import requests

logger = logging.getLogger('yt-local.covers')


COVER_SIZES = {
    'mqdefault':     'mqdefault.jpg',
    'hqdefault':     'hqdefault.jpg',
    'sddefault':     'sddefault.jpg',
    'maxresdefault': 'maxresdefault.jpg',
}


# Глобальная сессия — переиспользует TCP-соединения
_session = requests.Session()
_session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
})


def download_poster(
    video_id: str,
    output_path: Path,
    size: str = 'hqdefault',
    timeout: int = 15,
    normalize: bool = True,
    target_size: int = 480,
) -> bool:
    if size not in COVER_SIZES:
        logger.warning(f"Неизвестный размер обложки: {size}")
        return False

    url = f"https://img.youtube.com/vi/{video_id}/{COVER_SIZES[size]}"

    try:
        response = _session.get(url, timeout=timeout, stream=True)
        response.raise_for_status()
        if response.headers.get('Content-Length'):
            length = int(response.headers['Content-Length'])
            if length < 1500:
                return False
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
    except requests.RequestException as e:
        logger.warning(f"Не удалось скачать постер {size} для {video_id}: {e}")
        return False

    if not output_path.exists() or output_path.stat().st_size < 500:
        return False

    logger.info(f"Постер сохранён: {output_path.name} ({size})")

    if normalize:
        tmp = output_path.with_suffix('.raw.jpg')
        try:
            output_path.rename(tmp)
            if _normalize_poster(tmp, output_path, target_size):
                tmp.unlink()
            else:
                if tmp.exists() and not output_path.exists():
                    tmp.rename(output_path)
        except OSError:
            if tmp.exists() and not output_path.exists():
                try:
                    tmp.rename(output_path)
                except OSError:
                    pass

    return True


def _normalize_poster(input_path: Path, output_path: Path, size: int = 480) -> bool:
    """
    Приводит постер к квадрату size×size с кропом по центру.
    Если исходник меньше — апскейлит.
    """
    try:
        result = subprocess.run(
            [
                'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                '-i', str(input_path),
                '-vf', (
                    f'scale={size}:{size}:force_original_aspect_ratio=increase,'
                    f'crop={size}:{size}'
                ),
                '-q:v', '3',
                str(output_path),
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            logger.debug(f"ffmpeg нормализация: {result.stderr.strip()}")
            return False
        return output_path.exists() and output_path.stat().st_size > 500
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning(f"ffmpeg нормализация недоступна: {e}")
        return False


def extract_video_frame(
    video_path: Path,
    output_path: Path,
    second: int = 15,
    fallback_seconds: tuple[int, ...] = (1, 5, 10),
) -> bool:
    """Извлекает кадр из видео через ffmpeg на указанной секунде."""
    if not video_path.exists():
        logger.warning(f"Видео не найдено: {video_path}")
        return False

    output_path.parent.mkdir(parents=True, exist_ok=True)

    for sec in (second,) + fallback_seconds:
        if _run_ffmpeg_frame(video_path, output_path, sec):
            logger.info(f"Кадр извлечён с {sec} сек: {output_path.name}")
            return True

    logger.warning(f"Не удалось извлечь кадр из {video_path.name}")
    return False


def _run_ffmpeg_frame(video_path: Path, output_path: Path, second: int) -> bool:
    """Один прогон ffmpeg для извлечения кадра."""
    try:
        result = subprocess.run(
            [
                'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                '-ss', str(second),
                '-i', str(video_path),
                '-frames:v', '1',
                '-q:v', '2',
                '-vf', 'scale=640:-1',
                str(output_path),
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return False
        return output_path.exists() and output_path.stat().st_size > 1000
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.warning(f"ffmpeg кадр {second}с: {e}")
        return False


def get_cover_for_track(
    track_id: int,
    video_id: str,
    covers_dir: Path,
    mode: str = 'auto',
    video_path: Path | None = None,
    video_frame_second: int = 15,
) -> Path | None:
    """
    Возвращает путь к обложке для трека.
    mode:
        'poster'      — только постер
        'video_frame' — сначала кадр, fallback на постер
        'auto'        — если есть видео, сначала кадр, иначе постер
    """
    covers_dir.mkdir(parents=True, exist_ok=True)

    poster_path = covers_dir / f"{video_id}_poster.jpg"
    frame_path = covers_dir / f"{video_id}_frame.jpg"

    attempts: list[tuple[str, Path]] = []

    if mode == 'poster':
        attempts = [('poster', poster_path)]
    elif mode == 'video_frame':
        attempts = [('frame', frame_path), ('poster', poster_path)]
    else:  # auto
        if video_path and video_path.exists():
            attempts.append(('frame', frame_path))
        attempts.append(('poster', poster_path))

    for kind, path in attempts:
        # Уже есть — используем
        if path.exists() and path.stat().st_size > 1000:
            return path

        if kind == 'poster':
            if download_poster(video_id, path, size='hqdefault', normalize=True, target_size=480):
                return path
        elif kind == 'frame':
            if video_path and video_path.exists():
                if extract_video_frame(video_path, path, second=video_frame_second):
                    return path

    logger.warning(f"Обложка не получена для {video_id}")
    return None