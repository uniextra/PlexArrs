import importlib
import os
import unittest
from unittest.mock import patch


class TestConfig(unittest.TestCase):
    def _reload_config(self, env: dict[str, str]):
        with patch.dict(os.environ, env, clear=True):
            import config
            return importlib.reload(config)

    def test_is_configured(self):
        cfg = self._reload_config({})
        self.assertFalse(cfg.is_configured(None))
        self.assertFalse(cfg.is_configured(""))
        self.assertFalse(cfg.is_configured("   "))
        self.assertFalse(cfg.is_configured("YOUR_API_KEY_HERE"))
        self.assertTrue(cfg.is_configured("valid_key"))

    def test_parse_int_env_fallbacks(self):
        cfg = self._reload_config({
            "SONARR_ROOT_FOLDER_ID": "",
            "SONARR_QUALITY_PROFILE_ID": "abc",
            "RADARR_ROOT_FOLDER_ID": " 42 ",
        })
        self.assertEqual(cfg.SONARR_ROOT_FOLDER_ID, 1)
        self.assertEqual(cfg.SONARR_QUALITY_PROFILE_ID, 1)
        self.assertEqual(cfg.RADARR_ROOT_FOLDER_ID, 42)

    def test_allowed_user_ids_parsing(self):
        cfg = self._reload_config({"ALLOWED_USER_IDS": "YOUR_TELEGRAM_USER_ID_HERE"})
        self.assertIsNone(cfg.ALLOWED_USER_IDS)

        cfg = self._reload_config({"ALLOWED_USER_IDS": "123456, bad_id , 789012"})
        self.assertEqual(cfg.ALLOWED_USER_IDS, [123456, 789012])

    def test_holyarrs_auto_selected_and_endpoints(self):
        cfg = self._reload_config({
            "TELEGRAM_BOT_TOKEN": "123:token",
            "QBITTORRENT_URL": "http://localhost:8080",
            "HOLYARRS_URL": "http://192.168.1.100:6262/",
            "HOLYARRS_API_KEY": "holy_key",
        })
        cfg.validate_config()
        self.assertEqual(cfg.active_media_stack["mode"], "holyarrs")
        self.assertEqual(cfg.get_radarr_endpoint(), ("http://192.168.1.100:6262/radarr", "holy_key"))
        self.assertEqual(cfg.get_sonarr_endpoint(), ("http://192.168.1.100:6262/sonarr", "holy_key"))

    def test_arr_stack_and_hot_switch(self):
        cfg = self._reload_config({
            "TELEGRAM_BOT_TOKEN": "123:token",
            "QBITTORRENT_URL": "http://localhost:8080",
            "RADARR_URL": "http://localhost:7878",
            "RADARR_API_KEY": "radarr_key",
            "SONARR_URL": "http://localhost:8989",
            "SONARR_API_KEY": "sonarr_key",
            "HOLYARRS_URL": "http://localhost:6262",
            "HOLYARRS_API_KEY": "holy_key",
        })
        cfg.validate_config()
        self.assertEqual(cfg.active_media_stack["mode"], "arr")
        self.assertEqual(cfg.get_radarr_endpoint(), ("http://localhost:7878", "radarr_key"))
        self.assertEqual(cfg.get_sonarr_endpoint(), ("http://localhost:8989", "sonarr_key"))

        cfg.active_media_stack["mode"] = "holyarrs"
        self.assertEqual(cfg.get_radarr_endpoint(), ("http://localhost:6262/radarr", "holy_key"))
        self.assertEqual(cfg.get_sonarr_endpoint(), ("http://localhost:6262/sonarr", "holy_key"))

    def test_validate_config_exits_without_media_stack(self):
        cfg = self._reload_config({
            "TELEGRAM_BOT_TOKEN": "123:token",
            "QBITTORRENT_URL": "http://localhost:8080",
        })
        with self.assertRaises(SystemExit):
            cfg.validate_config()
