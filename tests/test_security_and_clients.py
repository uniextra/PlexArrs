import unittest
from unittest.mock import MagicMock, patch

import config
import radarr_client
import sonarr_client
import utils


class TestSecurityAndClients(unittest.TestCase):
    def test_is_user_allowed_fail_closed(self):
        with patch.object(utils, "ALLOWED_USER_IDS", None):
            self.assertFalse(utils.is_user_allowed(123456))
        with patch.object(utils, "ALLOWED_USER_IDS", []):
            self.assertFalse(utils.is_user_allowed(123456))
        with patch.object(utils, "ALLOWED_USER_IDS", [111, 222]):
            self.assertTrue(utils.is_user_allowed(111))
            self.assertFalse(utils.is_user_allowed(333))

    def test_unmonitor_movie_handles_empty_list(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_session = MagicMock()
        mock_session.put.return_value = mock_resp

        with patch.object(radarr_client, "get_radarr_endpoint", return_value=("http://radarr:7878", "key")), \
             patch.object(radarr_client, "get_http_session", return_value=mock_session):
            self.assertFalse(radarr_client.unmonitor_movie(99))

        mock_resp.json.return_value = [{"id": 99, "monitored": False}]
        with patch.object(radarr_client, "get_radarr_endpoint", return_value=("http://radarr:7878", "key")), \
             patch.object(radarr_client, "get_http_session", return_value=mock_session):
            self.assertTrue(radarr_client.unmonitor_movie(99))

    def test_unmonitor_series_handles_empty_list(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_session = MagicMock()
        mock_session.put.return_value = mock_resp

        with patch.object(sonarr_client, "get_sonarr_endpoint", return_value=("http://sonarr:8989", "key")), \
             patch.object(sonarr_client, "get_http_session", return_value=mock_session):
            self.assertFalse(sonarr_client.unmonitor_series(55))

        mock_resp.json.return_value = [{"id": 55, "monitored": False}]
        with patch.object(sonarr_client, "get_sonarr_endpoint", return_value=("http://sonarr:8989", "key")), \
             patch.object(sonarr_client, "get_http_session", return_value=mock_session):
            self.assertTrue(sonarr_client.unmonitor_series(55))

    def test_clients_respect_dynamic_stack_switch(self):
        with patch.object(config, "RADARR_URL", "http://radarr:7878"), \
             patch.object(config, "RADARR_API_KEY", "r_key"), \
             patch.object(config, "SONARR_URL", "http://sonarr:8989"), \
             patch.object(config, "SONARR_API_KEY", "s_key"), \
             patch.object(config, "HOLYARRS_URL", "http://holyarrs:6262"), \
             patch.object(config, "HOLYARRS_API_KEY", "h_key"), \
             patch.dict(config.active_media_stack, {"mode": "arr"}):

            with patch.object(radarr_client, "make_api_request", return_value=[]) as mock_radarr_req:
                radarr_client.search_radarr("Matrix")
                mock_radarr_req.assert_called_with("http://radarr:7878", "r_key", "movie/lookup", {"term": "Matrix"})

            config.active_media_stack["mode"] = "holyarrs"

            with patch.object(radarr_client, "make_api_request", return_value=[]) as mock_radarr_req, \
                 patch.object(sonarr_client, "make_api_request", return_value=[]) as mock_sonarr_req:
                radarr_client.search_radarr("Matrix")
                sonarr_client.search_sonarr("Dark")
                mock_radarr_req.assert_called_with("http://holyarrs:6262/radarr", "h_key", "movie/lookup", {"term": "Matrix"})
                mock_sonarr_req.assert_called_with("http://holyarrs:6262/sonarr", "h_key", "series/lookup", {"term": "Dark"})
