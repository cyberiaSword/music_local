"""
Тесты для core.settings и core.config.
"""

import json

import pytest

from core.config import AppConfig, CONFIG_VERSION
from core.settings import Settings


class TestAppConfig:
    """Тесты Pydantic-модели."""

    def test_defaults(self):
        """Дефолтные значения корректны."""
        cfg = AppConfig()
        assert cfg.player_volume == 70
        assert cfg.theme == 'dark'
        assert cfg.audio_quality_v0 is True
        assert cfg.proxy is None
        assert cfg.config_version == CONFIG_VERSION
        assert cfg.global_hotkeys_enabled is True

    def test_volume_validation_low(self):
        """volume < 0 — ошибка."""
        with pytest.raises(Exception):
            AppConfig(player_volume=-1)

    def test_volume_validation_high(self):
        """volume > 100 — ошибка."""
        with pytest.raises(Exception):
            AppConfig(player_volume=150)

    def test_proxy_validation_valid(self):
        """Валидные прокси принимаются."""
        cfg = AppConfig(proxy='http://127.0.0.1:7897')
        assert cfg.proxy == 'http://127.0.0.1:7897'

        cfg = AppConfig(proxy='socks5://127.0.0.1:1080')
        assert cfg.proxy == 'socks5://127.0.0.1:1080'

    def test_proxy_validation_empty(self):
        """Пустая строка превращается в None."""
        cfg = AppConfig(proxy='')
        assert cfg.proxy is None

    def test_proxy_validation_invalid(self):
        """Невалидный прокси — ошибка."""
        with pytest.raises(Exception):
            AppConfig(proxy='not-a-proxy')

    def test_theme_validation(self):
        """Тема должна быть из списка."""
        AppConfig(theme='dark')  # ок
        AppConfig(theme='light')  # ок
        AppConfig(theme='auto')   # ок
        with pytest.raises(Exception):
            AppConfig(theme='rainbow')

    def test_extra_keys_ignored(self):
        """Неизвестные ключи игнорируются."""
        cfg = AppConfig(unknown_key='value', player_volume=50)
        assert cfg.player_volume == 50
        assert not hasattr(cfg, 'unknown_key')


class TestSettings:
    """Тесты обёртки Settings."""

    def test_create_new(self, tmp_settings_path):
        """Создаёт файл настроек, если его нет."""
        s = Settings(tmp_settings_path)
        assert tmp_settings_path.exists()
        assert s.get('player_volume') == 70

    def test_save_and_load(self, tmp_settings_path):
        """Сохранение и загрузка работают."""
        s1 = Settings(tmp_settings_path)
        s1.set('player_volume', 85)
        s1.save()

        s2 = Settings(tmp_settings_path)
        assert s2.get('player_volume') == 85

    def test_global_hotkeys_default(self, tmp_settings_path):
        settings = Settings(tmp_settings_path)
        assert settings.get('global_hotkeys_enabled') is True
        assert settings.global_hotkeys_enabled is True
        assert settings['global_hotkeys_enabled'] is True
        assert settings.to_dict()['global_hotkeys_enabled'] is True

    def test_global_hotkeys_persistence(self, tmp_settings_path):
        settings = Settings(tmp_settings_path)
        settings.set('global_hotkeys_enabled', False)
        assert settings.global_hotkeys_enabled is False
        settings.save()

        data = json.loads(tmp_settings_path.read_text(encoding='utf-8'))
        assert data['global_hotkeys_enabled'] is False
        loaded = Settings(tmp_settings_path)
        assert loaded.get('global_hotkeys_enabled') is False
        loaded.global_hotkeys_enabled = True
        assert loaded['global_hotkeys_enabled'] is True
        loaded['global_hotkeys_enabled'] = False
        loaded.save()
        assert Settings(tmp_settings_path).global_hotkeys_enabled is False

    @pytest.mark.parametrize('version', [None, CONFIG_VERSION])
    def test_global_hotkeys_missing_from_old_json(self, tmp_settings_path, version):
        data = {'player_volume': 42}
        if version is not None:
            data['config_version'] = version
        tmp_settings_path.write_text(json.dumps(data), encoding='utf-8')
        settings = Settings(tmp_settings_path)
        assert settings.global_hotkeys_enabled is True
        assert settings.get('player_volume') == 42

    def test_get_default(self, tmp_settings_path):
        """get с дефолтом работает для несуществующего ключа."""
        s = Settings(tmp_settings_path)
        assert s.get('nonexistent', 'default') == 'default'
        assert s.get('nonexistent') is None

    def test_set_valid(self, tmp_settings_path):
        """Валидные значения сохраняются."""
        s = Settings(tmp_settings_path)
        s.set('player_volume', 90)
        assert s.get('player_volume') == 90

    def test_set_invalid_ignored(self, tmp_settings_path):
        """Невалидные значения не сохраняются."""
        s = Settings(tmp_settings_path)
        s.set('player_volume', 70)
        s.set('player_volume', 999)  # невалидно
        assert s.get('player_volume') == 70  # осталось прежним

    def test_set_unknown_key_ignored(self, tmp_settings_path):
        """Неизвестные ключи не сохраняются."""
        s = Settings(tmp_settings_path)
        s.set('unknown_key', 'value')
        assert s.get('unknown_key') is None

    def test_getitem(self, tmp_settings_path):
        """settings['key'] работает."""
        s = Settings(tmp_settings_path)
        assert s['player_volume'] == 70

    def test_contains(self, tmp_settings_path):
        """'key' in settings работает."""
        s = Settings(tmp_settings_path)
        assert 'player_volume' in s
        assert 'nonexistent' not in s

    def test_reset_to_defaults(self, tmp_settings_path):
        """Сброс к дефолтным значениям."""
        s = Settings(tmp_settings_path)
        s.set('player_volume', 20)
        s.reset_to_defaults()
        assert s.get('player_volume') == 70

    def test_old_settings_migration(self, tmp_settings_path):
        """Старые настройки без config_version загружаются."""
        # Пишем старый формат
        old = {'player_volume': 50, 'theme': 'dark'}
        with open(tmp_settings_path, 'w') as f:
            json.dump(old, f)

        s = Settings(tmp_settings_path)
        assert s.get('player_volume') == 50
        assert s.get('config_version') == CONFIG_VERSION