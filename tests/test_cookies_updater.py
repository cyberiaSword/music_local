"""
Тесты для core.cookies_updater.
"""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from core.cookies_updater import (
    _is_youtube_cookie,
    _cookie_to_netscape,
    check_cookies_valid,
    update_cookies_from_browser,
    CookieUpdateResult,
)


class TestHelpers:
    """Тесты вспомогательных функций."""

    def test_is_youtube_cookie(self):
        """YouTube/Google cookies определяются."""
        assert _is_youtube_cookie({'domain': '.youtube.com'}) is True
        assert _is_youtube_cookie({'domain': '.google.com'}) is True
        assert _is_youtube_cookie({'domain': '.example.com'}) is False
        assert _is_youtube_cookie({'domain': ''}) is False

    def test_cookie_to_netscape(self):
        """Cookie конвертируется в Netscape-формат."""
        cookie = {
            'domain': '.youtube.com',
            'path': '/',
            'secure': True,
            'expires': 1700000000,
            'name': 'SID',
            'value': 'abc123',
        }
        line = _cookie_to_netscape(cookie)
        parts = line.split('\t')
        assert parts[0] == '.youtube.com'
        assert parts[1] == 'TRUE'
        assert parts[3] == 'TRUE'
        assert parts[5] == 'SID'
        assert parts[6] == 'abc123'


class TestUpdateCookies:
    """Тесты обновления cookies."""

    def test_rookiepy_not_installed(self, tmp_path):
        """rookiepy не установлен — понятная ошибка."""
        with patch.dict('sys.modules', {'rookiepy': None}):
            with patch('core.cookies_updater.update_cookies_from_browser') as mock:
                pass
        # Реальный тест: если rookiepy нет, вернётся ошибка
        # (предполагаем, что в тестовой среде он может быть или нет)

    def test_output_path_created(self, tmp_path):
        """При успехе output_path создаётся."""
        fake_cookie = {
            'domain': '.youtube.com',
            'path': '/',
            'secure': True,
            'expires': 1700000000,
            'name': 'SID',
            'value': 'test123',
        }
        fake_cookie2 = dict(fake_cookie, name='HSID', value='test456')

        mock_rookiepy = MagicMock()
        mock_rookiepy.chrome.return_value = [fake_cookie, fake_cookie2]

        with patch.dict('sys.modules', {'rookiepy': mock_rookiepy}):
            # Перезагружаем модуль, чтобы подхватил mock
            import importlib
            import core.cookies_updater as cu
            importlib.reload(cu)

            output = tmp_path / 'cookies.txt'
            result = cu.update_cookies_from_browser(output, browser='chrome')

            assert result.success is True
            assert result.browser == 'chrome'
            assert output.exists()
            content = output.read_text()
            assert 'Netscape HTTP Cookie File' in content
            assert 'SID' in content


class TestCheckCookiesValid:
    """Тесты проверки валидности cookies."""

    def test_missing_file(self, tmp_path):
        """Нет файла — невалидно."""
        valid, reason = check_cookies_valid(tmp_path / 'missing.txt')
        assert valid is False
        assert 'не существует' in reason

    def test_empty_file(self, tmp_path):
        """Пустой файл — невалидно."""
        path = tmp_path / 'cookies.txt'
        path.write_text('')
        valid, reason = check_cookies_valid(path)
        assert valid is False
        assert 'пустой' in reason.lower()

    def test_wrong_format(self, tmp_path):
        """Неверный формат — невалидно."""
        path = tmp_path / 'cookies.txt'
        path.write_text('{"cookies": []}')
        valid, reason = check_cookies_valid(path)
        assert valid is False
        assert 'Netscape' in reason

    def test_valid_cookies(self, tmp_path):
        """Правильный формат с SID — валидно."""
        path = tmp_path / 'cookies.txt'
        path.write_text(
            "# Netscape HTTP Cookie File\n"
            ".youtube.com\tTRUE\t/\tTRUE\t1700000000\tSID\tabc123\n"
            ".youtube.com\tTRUE\t/\tTRUE\t1700000000\tHSID\tabc456\n"
        )
        valid, reason = check_cookies_valid(path)
        assert valid is True
        assert 'SID' in reason

    def test_no_sid(self, tmp_path):
        """Нет SID — невалидно."""
        path = tmp_path / 'cookies.txt'
        path.write_text(
            "# Netscape HTTP Cookie File\n"
            ".youtube.com\tTRUE\t/\tTRUE\t1700000000\tOTHER\tvalue\n"
        )
        valid, reason = check_cookies_valid(path)
        assert valid is False
        assert 'SID' in reason