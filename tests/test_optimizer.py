"""
Тесты для core.optimizer.

Тесты, требующие ffmpeg, помечены @pytest.mark.integration
и пропускаются, если ffmpeg не установлен.
"""

import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from core.optimizer import OptimizeResult, optimize_file


def _ffmpeg_available() -> bool:
    """Проверяет, доступен ли ffmpeg."""
    return shutil.which('ffmpeg') is not None


class TestOptimizeFile:
    """Тесты optimize_file."""

    def test_nonexistent_file(self, tmp_path):
        """Несуществующий файл — skipped."""
        path = tmp_path / 'nonexistent.mp3'
        result = optimize_file(path)
        assert result.action == 'skipped'
        assert 'не MP3' in result.message

    def test_non_mp3_file(self, tmp_path):
        """Не-MP3 файл — skipped."""
        path = tmp_path / 'test.txt'
        path.write_text('not mp3')
        result = optimize_file(path)
        assert result.action == 'skipped'

    def test_dry_run(self, tmp_path):
        """Dry-run не меняет файл."""
        mp3 = tmp_path / 'test.mp3'
        mp3.write_bytes(b'fake mp3 data' * 1000)

        # Мокаем ffprobe, чтобы вернул высокий битрейт
        with patch('core.optimizer._ffprobe_bitrate', return_value=320):
            result = optimize_file(mp3, dry_run=True)
            assert result.action == 'optimized'
            assert '[DRY RUN]' in result.message
            # Файл не изменился
            assert mp3.read_bytes() == b'fake mp3 data' * 1000

    def test_low_bitrate_skipped(self, tmp_path):
        """Низкий битрейт — skipped."""
        mp3 = tmp_path / 'test.mp3'
        mp3.write_bytes(b'fake' * 100)

        with patch('core.optimizer._ffprobe_bitrate', return_value=128):
            result = optimize_file(mp3, threshold_kbps=250)
            assert result.action == 'skipped'
            assert '128' in result.message

    def test_ffprobe_error(self, tmp_path):
        """Ошибка ffprobe — failed."""
        mp3 = tmp_path / 'test.mp3'
        mp3.write_bytes(b'fake')

        with patch('core.optimizer._ffprobe_bitrate', return_value=None):
            result = optimize_file(mp3)
            assert result.action == 'failed'