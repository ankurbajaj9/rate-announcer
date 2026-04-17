import os
import unittest
from unittest.mock import patch, MagicMock, mock_open
from datetime import datetime, date
import pandas as pd

from src.monitor import (
    eur_mwh_to_sek_kwh,
    is_quiet_hour,
    get_local_ip,
    get_eur_to_sek,
    fetch_quarter_prices,
    notify_google_home,
)

class TestMonitor(unittest.TestCase):

    def test_eur_mwh_to_sek_kwh(self):
        """Test the conversion calculation."""
        self.assertAlmostEqual(eur_mwh_to_sek_kwh(100.0, 11.5), 1.15)
        self.assertAlmostEqual(eur_mwh_to_sek_kwh(0.0, 10.0), 0.0)
        self.assertAlmostEqual(eur_mwh_to_sek_kwh(50.0, 12.0), 0.6)

    @patch("src.monitor.QUIET_HOURS_START", 22)
    @patch("src.monitor.QUIET_HOURS_END", 7)
    def test_is_quiet_hour(self):
        """Test time bounds for quiet hours."""
        # 11 PM should be quiet
        self.assertTrue(is_quiet_hour(datetime(2026, 4, 15, 23, 0)))
        # 3 AM should be quiet
        self.assertTrue(is_quiet_hour(datetime(2026, 4, 15, 3, 0)))
        # 12 PM should not be quiet
        self.assertFalse(is_quiet_hour(datetime(2026, 4, 15, 12, 0)))

    @patch("src.monitor.socket.socket")
    def test_get_local_ip(self, mock_socket):
        """Test local IP retrieval."""
        mock_instance = mock_socket.return_value
        mock_instance.getsockname.return_value = ("192.168.1.50", 12345)
        self.assertEqual(get_local_ip(), "192.168.1.50")

    @patch("src.monitor.requests.get")
    def test_get_eur_to_sek_success(self, mock_get):
        """Test fetching FX rates successfully."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"rates": {"SEK": 11.23}}
        mock_get.return_value = mock_resp
        
        # Test without touching the file system cache
        with patch("src.monitor.os.path.exists", return_value=False), \
             patch("builtins.open", mock_open()):
            rate = get_eur_to_sek(date(2026, 4, 17))
            self.assertEqual(rate, 11.23)

    @patch("src.monitor.requests.get")
    def test_get_eur_to_sek_fallback(self, mock_get):
        """Test fallback FX rate on failure."""
        mock_get.side_effect = Exception("Network error")
        
        with patch("src.monitor.os.path.exists", return_value=False):
            rate = get_eur_to_sek(date(2026, 4, 17))
            self.assertEqual(rate, 11.0) # Fallback rate

    @patch("entsoe.EntsoePandasClient")
    def test_fetch_quarter_prices(self, mock_client_class):
        """Test querying ENTSO-E and resampling."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        tz = "Europe/Stockholm"
        start = pd.Timestamp("2026-04-17", tz=tz)
        times = pd.date_range(start, periods=2, freq="1h")
        mock_prices = pd.Series([100.0, 150.0], index=times)
        
        mock_client.query_day_ahead_prices.return_value = mock_prices
        
        with patch("src.monitor.os.path.exists", return_value=False), \
             patch("pandas.to_pickle"):
            result = fetch_quarter_prices(start.date())
            
            # Resampling 1h into 15m intervals
            self.assertEqual(len(result), 5)
            self.assertEqual(result.iloc[0], 100.0)
            self.assertEqual(result.iloc[-1], 150.0)

    @patch("src.monitor.pychromecast")
    @patch("src.monitor.gTTS")
    @patch("src.monitor.http.server.HTTPServer")
    def test_notify_google_home_success(self, mock_server, mock_gtts, mock_chromecast):
        """Test a successful Google Home notification."""
        # Mock gTTS explicitly
        mock_gtts_instance = MagicMock()
        mock_gtts.return_value = mock_gtts_instance
        
        # Mock chromecast device and browser
        mock_cast = MagicMock()
        mock_browser = MagicMock()
        mock_chromecast.get_listed_chromecasts.return_value = ([mock_cast], mock_browser)
        
        # Speed up test execution by overriding time.sleep
        with patch("src.monitor.time.sleep"):
            success = notify_google_home("Test message")
            
            # Verifications
            self.assertTrue(success)
            mock_gtts.assert_called_once()
            mock_chromecast.get_listed_chromecasts.assert_called_once()
            mock_cast.wait.assert_called_once()
            mock_cast.media_controller.play_media.assert_called_once()
            mock_cast.media_controller.block_until_active.assert_called_once()
            mock_browser.stop_discovery.assert_called_once()

    @patch("src.monitor.pychromecast")
    @patch("src.monitor.gTTS")
    @patch("src.monitor.http.server.HTTPServer")
    def test_notify_google_home_not_found(self, mock_server, mock_gtts, mock_chromecast):
        """Test notification when the Google Home device is not found."""
        mock_browser = MagicMock()
        # Return empty list for chromecasts
        mock_chromecast.get_listed_chromecasts.return_value = ([], mock_browser)
        
        success = notify_google_home("Test message")
        
        self.assertFalse(success)
        mock_browser.stop_discovery.assert_called_once()

    @patch("src.monitor.pychromecast")
    @patch("src.monitor.gTTS")
    @patch("src.monitor.http.server.HTTPServer")
    def test_notify_google_home_exception(self, mock_server, mock_gtts, mock_chromecast):
        """Test notification handles exceptions gracefully."""
        mock_chromecast.get_listed_chromecasts.side_effect = Exception("Network discovery failed")
        
        success = notify_google_home("Test message")
        self.assertFalse(success)

if __name__ == "__main__":
    unittest.main()
