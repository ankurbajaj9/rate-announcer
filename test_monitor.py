import os
import unittest
from unittest.mock import patch, MagicMock, mock_open
from datetime import datetime, date, timedelta
import pandas as pd

from src.monitor import _build_summary_message, is_quiet_hour
from src.notify import get_local_ip, notify_google_home
from src.prices import eur_mwh_to_sek_kwh, fetch_quarter_prices, get_eur_to_sek

class TestMonitor(unittest.TestCase):

    def test_build_summary_message(self):
        """Test that _build_summary_message produces the correct summary string."""
        msg = _build_summary_message(
            "today",
            75.0,
            (120.5, "14:00"),
            (30.2, "03:00"),
        )
        expected = (
            "I have fetched the electricity rates for today. "
            "The average price is 75.0 öre per kilowatt hour. "
            "The maximum price will be 120.5 öre at 14:00, "
            "and the minimum will be 30.2 öre at 03:00."
        )
        self.assertEqual(msg, expected)

    def test_build_summary_message_tomorrow(self):
        """Test that day_word is correctly included in the summary."""
        msg = _build_summary_message(
            "tomorrow",
            50.0,
            (95.0, "09:00"),
            (20.0, "16:00"),
        )
        self.assertIn("tomorrow", msg)
        self.assertNotIn("today", msg)

    
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

    @patch("src.notify.get_local_ip", return_value="127.0.0.1")
    @patch("src.notify.zeroconf.Zeroconf")
    @patch("src.notify.pychromecast")
    @patch("src.notify.gTTS")
    @patch("src.notify.http.server.HTTPServer")
    def test_notify_google_home_success(self, mock_server, mock_gtts, mock_chromecast, mock_zeroconf, mock_local_ip):
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
            mock_cast.disconnect.assert_called_once_with(timeout=5)
            mock_browser.stop_discovery.assert_called_once()

    @patch("src.notify.get_local_ip", return_value="127.0.0.1")
    @patch("src.notify.zeroconf.Zeroconf")
    @patch("src.notify.pychromecast")
    @patch("src.notify.gTTS")
    @patch("src.notify.http.server.HTTPServer")
    def test_notify_google_home_playback_not_started(self, mock_server, mock_gtts, mock_chromecast, mock_zeroconf, mock_local_ip):
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
            mock_cast.reset_mock()
            mock_cast.media_controller.status.player_state = "IDLE"
            mock_cast.media_controller.status.idle_reason = idle_reason
            with self.subTest(idle_reason=idle_reason):
                with patch("src.notify.time.sleep"):
                    success = notify_google_home("Test message")
                self.assertFalse(success)
                mock_cast.disconnect.assert_called_once_with(timeout=5)

    @patch("src.notify.get_local_ip", return_value="127.0.0.1")
    @patch("src.notify.zeroconf.Zeroconf")
    @patch("src.notify.pychromecast")
    @patch("src.notify.gTTS")
    @patch("src.notify.http.server.HTTPServer")
    def test_notify_google_home_not_found(self, mock_server, mock_gtts, mock_chromecast, mock_zeroconf, mock_local_ip):
        """Test notification when the Google Home device is not found."""
        mock_browser = MagicMock()
        mock_chromecast.discovery.CastBrowser.return_value = mock_browser
        
        # Fast fail event wait
        with patch("src.notify.threading.Event.wait") as mock_wait:
            mock_wait.return_value = False
            success = notify_google_home("Test message")
        
        self.assertFalse(success)
        mock_browser.stop_discovery.assert_called_once()

    @patch("src.notify.get_local_ip", return_value="127.0.0.1")
    @patch("src.notify.zeroconf.Zeroconf")
    @patch("src.notify.pychromecast")
    @patch("src.notify.gTTS")
    @patch("src.notify.http.server.HTTPServer")
    def test_notify_google_home_exception(self, mock_server, mock_g, mock_chromecast, mock_zeroconf, mock_local_ip):
        """Test notification handles exceptions gracefully."""
        mock_chromecast.discovery.CastBrowser.side_effect = Exception("Network discovery failed")
        
        success = notify_google_home("Test message")
        self.assertFalse(success)

    @patch("src.monitor.scheduler")
    @patch("src.monitor.is_quiet_hour", return_value=False)
    @patch("src.monitor.get_eur_to_sek", return_value=11.0)
    @patch("src.monitor.fetch_quarter_prices")
    def test_plan_day_force_summary_schedules_when_cached(
        self, mock_fetch, mock_fx, mock_quiet, mock_scheduler
    ):
        """Summary job is scheduled on startup even when prices come from cache."""
        from src.monitor import plan_day

        tz = "Europe/Stockholm"
        # Build timestamps that are always in the past relative to now
        now_aware = pd.Timestamp.now(tz=tz)
        times = pd.date_range(now_aware - pd.Timedelta(hours=4), periods=4, freq="1h")
        mock_prices = pd.Series([50.0, 80.0, 60.0, 70.0], index=times)
        # Simulate cached prices (is_new_fetch=False)
        mock_fetch.return_value = (mock_prices, False)

        # force_summary=True → summary must be scheduled despite is_new_fetch=False
        plan_day(date.today(), force_summary=True)
        self.assertTrue(mock_scheduler.add_job.called)

        # Reset and verify that without force_summary, no job is added
        mock_scheduler.reset_mock()
        plan_day(date.today(), force_summary=False)
        # No summary job (is_new_fetch=False), no alert jobs (all times in the past)
        mock_scheduler.add_job.assert_not_called()

    @patch("src.monitor.log")
    @patch("src.monitor.scheduler")
    def test_log_next_notification_logs_next_run(self, mock_scheduler, mock_log):
        """Logs the nearest upcoming Google Home notification."""
        from src.monitor import _log_next_notification
        from src.notify import notify_google_home

        future_soon = datetime.now() + timedelta(minutes=3)
        future_later = datetime.now() + timedelta(minutes=10)

        soon_job = MagicMock(func=notify_google_home, next_run_time=future_soon)
        later_job = MagicMock(func=notify_google_home, next_run_time=future_later)
        planner_job = MagicMock(func=MagicMock(), next_run_time=future_soon)
        mock_scheduler.get_jobs.return_value = [later_job, planner_job, soon_job]

        _log_next_notification()

        self.assertEqual(mock_log.info.call_args_list[-1].args[0], "Next Google Home notification is scheduled for %s (in %d minute(s)).")
        self.assertEqual(mock_log.info.call_args_list[-1].args[1], future_soon.strftime("%Y-%m-%d %H:%M:%S %Z"))
        self.assertIn(mock_log.info.call_args_list[-1].args[2], (2, 3))

    @patch("src.monitor.log")
    @patch("src.monitor.scheduler")
    def test_log_next_notification_logs_when_none(self, mock_scheduler, mock_log):
        """Logs when no future Google Home notification is available."""
        from src.monitor import _log_next_notification
        from src.notify import notify_google_home

        past_job = MagicMock(func=notify_google_home, next_run_time=datetime.now() - timedelta(minutes=1))
        mock_scheduler.get_jobs.return_value = [past_job]

        _log_next_notification()

        mock_log.info.assert_called_with("No upcoming Google Home notifications are currently scheduled.")

    @patch("src.monitor._log_next_notification")
    @patch("src.monitor.plan_day")
    @patch("src.monitor.scheduler")
    def test_start_scheduler_reports_next_notification(self, mock_scheduler, mock_plan_day, mock_next_log):
        """Startup reports next notification timing."""
        from src.monitor import start_scheduler

        start_scheduler()

        mock_scheduler.start.assert_called_once()
        mock_plan_day.assert_called_once_with(date.today(), force_summary=True)
        mock_next_log.assert_called_once()

if __name__ == "__main__":
    unittest.main()
