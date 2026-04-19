import os
import unittest
from unittest.mock import patch, MagicMock, mock_open
from datetime import datetime, date
import pandas as pd

from src.monitor import is_quiet_hour
from src.notify import get_local_ip, notify_google_home
from src.prices import eur_mwh_to_sek_kwh, fetch_quarter_prices, get_eur_to_sek

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

    @patch("src.notify.socket.socket")
    def test_get_local_ip(self, mock_socket):
        """Test local IP retrieval."""
        mock_instance = mock_socket.return_value
        mock_instance.getsockname.return_value = ("192.168.1.50", 12345)
        self.assertEqual(get_local_ip(), "192.168.1.50")

    @patch("src.prices.requests.get")
    def test_get_eur_to_sek_success(self, mock_get):
        """Test fetching FX rates successfully."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"rates": {"SEK": 11.23}}
        mock_get.return_value = mock_resp
        
        # Test without touching the file system cache
        with patch("src.prices.os.path.exists", return_value=False), \
             patch("builtins.open", mock_open()):
            rate = get_eur_to_sek(date(2026, 4, 17))
            self.assertEqual(rate, 11.23)

    @patch("src.prices.requests.get")
    def test_get_eur_to_sek_fallback(self, mock_get):
        """Test fallback FX rate on failure."""
        mock_get.side_effect = Exception("Network error")
        
        with patch("src.prices.os.path.exists", return_value=False):
            rate = get_eur_to_sek(date(2026, 4, 17))
            self.assertEqual(rate, 11.0) # Fallback rate

    @patch("src.prices.EntsoePandasClient")
    def test_fetch_quarter_prices(self, mock_client_class):
        """Test querying ENTSO-E and resampling."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        tz = "Europe/Stockholm"
        start = pd.Timestamp("2026-04-17", tz=tz)
        times = pd.date_range(start, periods=2, freq="1h")
        mock_prices = pd.Series([100.0, 150.0], index=times)
        
        mock_client.query_day_ahead_prices.return_value = mock_prices
        
        with patch("src.prices.os.path.exists", return_value=False), \
             patch("pandas.to_pickle"):
            result, is_new = fetch_quarter_prices(start.date())
            
            # Resampling 1h into 15m intervals
            self.assertEqual(len(result), 5)
            self.assertTrue(is_new)
            self.assertEqual(result.iloc[0], 100.0)
            self.assertEqual(result.iloc[-1], 150.0)

    @patch("src.notify.zeroconf.Zeroconf")
    @patch("src.notify.pychromecast")
    @patch("src.notify.gTTS")
    @patch("src.notify.http.server.HTTPServer")
    def test_notify_google_home_success(self, mock_server, mock_gtts, mock_chromecast, mock_zeroconf):
        """Test a successful Google Home notification."""
        # Mock gTTS explicitly
        mock_gtts_instance = MagicMock()
        mock_gtts.return_value = mock_gtts_instance
        
        # Mock chromecast device and browser
        mock_cast = MagicMock()
        mock_cast_info = MagicMock()
        mock_cast_info.friendly_name = "Your Google Home Name"
        
        mock_browser = MagicMock()
        mock_browser.devices = {"mock_uuid": mock_cast_info}
        
        mock_chromecast.discovery.CastBrowser.return_value = mock_browser
        mock_chromecast.get_chromecast_from_cast_info.return_value = mock_cast
        mock_cast.media_controller.status.player_state = "PLAYING"
        mock_cast.media_controller.status.idle_reason = None
        
        # We need to trigger the callback when start_discovery is called
        def mock_start_discovery():
            # Get the callback passed to SimpleCastListener
            add_cb = mock_chromecast.discovery.SimpleCastListener.call_args[1]["add_callback"]
            # Trigger its add_callback
            add_cb("mock_uuid", "mock_service")
            
        mock_browser.start_discovery.side_effect = mock_start_discovery
        
        # Speed up test execution by overriding time.sleep
        with patch("src.notify.time.sleep"):
            success = notify_google_home("Test message")
            
            # Verifications
            self.assertTrue(success)
            mock_gtts.assert_called_once()
            mock_chromecast.discovery.CastBrowser.assert_called_once()
            mock_cast.wait.assert_called_once()
            mock_cast.media_controller.play_media.assert_called_once()
            mock_cast.media_controller.block_until_active.assert_called_once()
            mock_cast.media_controller.update_status.assert_called()
            mock_browser.stop_discovery.assert_called_once()

    @patch("src.notify.zeroconf.Zeroconf")
    @patch("src.notify.pychromecast")
    @patch("src.notify.gTTS")
    @patch("src.notify.http.server.HTTPServer")
    def test_notify_google_home_playback_not_started(self, mock_server, mock_gtts, mock_chromecast, mock_zeroconf):
        """Test notification returns false when Chromecast fails to start playback."""
        mock_cast = MagicMock()
        mock_cast_info = MagicMock()
        mock_cast_info.friendly_name = "Your Google Home Name"

        mock_browser = MagicMock()
        mock_browser.devices = {"mock_uuid": mock_cast_info}

        mock_chromecast.discovery.CastBrowser.return_value = mock_browser
        mock_chromecast.get_chromecast_from_cast_info.return_value = mock_cast

        def mock_start_discovery():
            add_cb = mock_chromecast.discovery.SimpleCastListener.call_args[1]["add_callback"]
            add_cb("mock_uuid", "mock_service")

        mock_browser.start_discovery.side_effect = mock_start_discovery

        for idle_reason in ("ERROR", "CANCELLED", "INTERRUPTED"):
            mock_cast.media_controller.status.player_state = "IDLE"
            mock_cast.media_controller.status.idle_reason = idle_reason
            with self.subTest(idle_reason=idle_reason):
                with patch("src.notify.time.sleep"):
                    success = notify_google_home("Test message")
                self.assertFalse(success)

    @patch("src.notify.zeroconf.Zeroconf")
    @patch("src.notify.pychromecast")
    @patch("src.notify.gTTS")
    @patch("src.notify.http.server.HTTPServer")
    def test_notify_google_home_not_found(self, mock_server, mock_gtts, mock_chromecast, mock_zeroconf):
        """Test notification when the Google Home device is not found."""
        mock_browser = MagicMock()
        mock_chromecast.discovery.CastBrowser.return_value = mock_browser
        
        # Fast fail event wait
        with patch("src.notify.threading.Event.wait") as mock_wait:
            mock_wait.return_value = False
            success = notify_google_home("Test message")
        
        self.assertFalse(success)
        mock_browser.stop_discovery.assert_called_once()

    @patch("src.notify.zeroconf.Zeroconf")
    @patch("src.notify.pychromecast")
    @patch("src.notify.gTTS")
    @patch("src.notify.http.server.HTTPServer")
    def test_notify_google_home_exception(self, mock_server, mock_g, mock_chromecast, mock_zeroconf):
        """Test notification handles exceptions gracefully."""
        mock_chromecast.discovery.CastBrowser.side_effect = Exception("Network discovery failed")
        
        success = notify_google_home("Test message")
        self.assertFalse(success)

if __name__ == "__main__":
    unittest.main()
