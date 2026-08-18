import os
import unittest
from unittest.mock import patch, MagicMock, mock_open, call
from datetime import datetime, date, timedelta
import pandas as pd
import requests

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
            "Summary for today: avg 75.0 öre; "
            "max 120.5 öre at 14:00; min 30.2 öre at 03:00."
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

    @patch("src.prices.lookup_area")
    @patch("src.prices.EntsoePandasClient")
    def test_fetch_quarter_prices_retries_exact_window_on_http_400(
        self, mock_client_class, mock_lookup_area
    ):
        """HTTP 400 from padded query should retry with exact day window."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        mock_lookup_area.return_value = "SE3_AREA"

        tz = "Europe/Stockholm"
        start = pd.Timestamp("2026-04-17", tz=tz)
        times = pd.date_range(start, periods=2, freq="1h")
        fallback_prices = pd.Series([100.0, 150.0], index=times)

        response = MagicMock(status_code=400)
        mock_client.query_day_ahead_prices.side_effect = requests.exceptions.HTTPError(response=response)
        mock_client._query_day_ahead_prices.return_value = fallback_prices

        with patch("src.prices.os.path.exists", return_value=False), \
             patch("pandas.to_pickle"):
            result, is_new = fetch_quarter_prices(start.date())

        self.assertTrue(is_new)
        self.assertEqual(len(result), 5)
        mock_lookup_area.assert_called_once()
        mock_client._query_day_ahead_prices.assert_called_once()

    @patch("src.prices.time.sleep")
    @patch("src.prices.EntsoePandasClient")
    def test_fetch_quarter_prices_retries_with_exponential_backoff(
        self, mock_client_class, mock_sleep
    ):
        """Future-day fetch retries with exponential backoff on transient failures."""
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client

        tomorrow = date.today() + timedelta(days=1)
        tz = "Europe/Stockholm"
        start = pd.Timestamp(tomorrow, tz=tz)
        times = pd.date_range(start, periods=2, freq="1h")
        mock_prices = pd.Series([100.0, 150.0], index=times)

        mock_client.query_day_ahead_prices.side_effect = [
            requests.exceptions.ConnectionError("temporary network issue"),
            requests.exceptions.ConnectionError("temporary network issue"),
            mock_prices,
        ]

        with patch("src.prices.os.path.exists", return_value=False), \
             patch("pandas.to_pickle"):
            result, is_new = fetch_quarter_prices(tomorrow)

        self.assertTrue(is_new)
        self.assertEqual(len(result), 5)
        self.assertEqual(mock_sleep.call_args_list, [call(30), call(60)])

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
        mock_cast_info.host = "192.168.1.100"
        mock_cast_info.port = 8009

        mock_browser = MagicMock()
        mock_browser.devices = {"mock_uuid": mock_cast_info}
        
        mock_chromecast.discovery.CastBrowser.return_value = mock_browser
        mock_chromecast.get_chromecast_from_host.return_value = mock_cast
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
            # Discovery is torn down immediately; cast is created via direct IP.
            mock_browser.stop_discovery.assert_called_once()
            mock_chromecast.get_chromecast_from_host.assert_called_once_with(
                ("192.168.1.100", 8009, mock_cast_info.uuid, mock_cast_info.model_name, "Your Google Home Name")
            )
            mock_cast.wait.assert_called_once()
            mock_cast.media_controller.play_media.assert_called_once()
            mock_cast.media_controller.block_until_active.assert_called_once()
            mock_cast.media_controller.update_status.assert_called()
            mock_cast.disconnect.assert_called_once_with(timeout=5)

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
        mock_cast_info.host = "192.168.1.100"
        mock_cast_info.port = 8009

        mock_browser = MagicMock()
        mock_browser.devices = {"mock_uuid": mock_cast_info}

        mock_chromecast.discovery.CastBrowser.return_value = mock_browser
        mock_chromecast.get_chromecast_from_host.return_value = mock_cast

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

    @patch("src.notify.GOOGLE_HOME_HOST", "192.168.0.82")
    @patch("src.notify.GOOGLE_HOME_PORT", 8009)
    @patch("src.notify.get_local_ip", return_value="127.0.0.1")
    @patch("src.notify.pychromecast")
    @patch("src.notify.gTTS")
    @patch("src.notify.http.server.HTTPServer")
    def test_notify_google_home_direct_host(self, mock_server, mock_gtts, mock_chromecast, mock_local_ip):
        """When GOOGLE_HOME_HOST is set, mDNS discovery is skipped entirely."""
        mock_cast = MagicMock()
        mock_chromecast.get_chromecast_from_host.return_value = mock_cast
        mock_cast.media_controller.status.player_state = "PLAYING"
        mock_cast.media_controller.status.idle_reason = None

        with patch("src.notify.time.sleep"):
            success = notify_google_home("Direct host test")

        self.assertTrue(success)
        # No mDNS browser should have been created
        mock_chromecast.discovery.CastBrowser.assert_not_called()
        # Cast must be created with direct host info (None uuid/model_name, name from config)
        mock_chromecast.get_chromecast_from_host.assert_called_once_with(
            ("192.168.0.82", 8009, None, None, "Your Google Home Name")
        )
        mock_cast.wait.assert_called_once()
        mock_cast.media_controller.play_media.assert_called_once()

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

    @patch("src.monitor.ALERT_OFFSET_MINUTES", 1)
    @patch("src.monitor.scheduler")
    @patch("src.monitor.is_quiet_hour", return_value=False)
    @patch("src.monitor.get_eur_to_sek", return_value=11.0)
    @patch("src.monitor.fetch_quarter_prices")
    def test_alerts_scheduled_one_minute_before_slot(
        self, mock_fetch, mock_fx, mock_quiet, mock_scheduler
    ):
        """High-price alerts should be scheduled one minute before the slot."""
        from src.monitor import plan_day

        tz = "Europe/Stockholm"
        # fixed now is 2026-04-20 10:00
        fixed_now = datetime(2026, 4, 20, 10, 0, 0)

        # Build future times where a high-price entry exists at the second slot
        times = pd.date_range("2026-04-20 10:15", periods=3, freq="15min", tz=tz)
        # Values: middle slot is the daily max and thus qualifies as entering high
        mock_prices = pd.Series([50.0, 90.0, 60.0], index=times)
        mock_fetch.return_value = (mock_prices, True)

        # Ensure datetime.now(tz) returns a tz-aware fixed time matching scheduled comparisons
        def now_side_effect(tzarg=None):
            if tzarg:
                return datetime(2026, 4, 20, 10, 0, 0, tzinfo=tzarg)
            return fixed_now

        with patch("src.monitor.datetime") as mock_datetime:
            mock_datetime.now.side_effect = now_side_effect

            plan_day(date(2026, 4, 20), force_summary=False)

        # Find a scheduled add_job call with run_date == (times[1] - 1 minute)
        expected_run = (times[1].to_pydatetime() - timedelta(minutes=1))
        found = False
        for call in mock_scheduler.add_job.call_args_list:
            rd = call.kwargs.get("run_date")
            if rd == expected_run:
                found = True
                break

        self.assertTrue(found, f"No add_job call scheduled at {expected_run}")

    @patch("src.monitor.ALERT_OFFSET_MINUTES", 1)
    @patch("src.monitor.scheduler")
    @patch("src.monitor.is_quiet_hour", return_value=False)
    @patch("src.monitor.get_eur_to_sek", return_value=11.0)
    @patch("src.monitor.fetch_quarter_prices")
    def test_alerts_fire_immediately_when_restart_mid_peak(
        self, mock_fetch, mock_fx, mock_quiet, mock_scheduler
    ):
        """A restart during an active peak should still announce it immediately."""
        from src.monitor import plan_day

        tz = "Europe/Stockholm"
        fixed_now = pd.Timestamp("2026-04-20 10:50", tz=tz).to_pydatetime()
        times = pd.date_range("2026-04-20 10:15", periods=4, freq="15min", tz=tz)
        mock_prices = pd.Series([50.0, 90.0, 90.0, 60.0], index=times)
        mock_fetch.return_value = (mock_prices, False)

        def now_side_effect(tzarg=None):
            if tzarg:
                return fixed_now.astimezone(tzarg)
            return fixed_now

        with patch("src.monitor.datetime") as mock_datetime:
            mock_datetime.now.side_effect = now_side_effect
            plan_day(date(2026, 4, 20), force_summary=False)

        found = False
        for call_args in mock_scheduler.add_job.call_args_list:
            if (
                call_args.args[:2] == (notify_google_home, "date")
                and call_args.kwargs.get("run_date") == fixed_now
            ):
                found = True
                break

        self.assertTrue(found, "No immediate alert was scheduled during the active peak.")

    @patch("src.monitor.log")
    @patch("src.monitor.scheduler")
    def test_log_next_notification_logs_next_run(self, mock_scheduler, mock_log):
        """Logs the nearest upcoming Google Home notification."""
        from src.monitor import _log_next_notification
        from src.notify import notify_google_home

        fixed_now = datetime(2026, 4, 20, 5, 0, 0)
        future_soon = fixed_now + timedelta(minutes=3)
        future_later = fixed_now + timedelta(minutes=10)

        soon_job = MagicMock(func=notify_google_home, next_run_time=future_soon)
        later_job = MagicMock(func=notify_google_home, next_run_time=future_later)
        planner_job = MagicMock(func=MagicMock(), next_run_time=future_soon)
        mock_scheduler.get_jobs.return_value = [later_job, planner_job, soon_job]

        with patch("src.monitor.datetime") as mock_datetime:
            mock_datetime.now.return_value = fixed_now
            _log_next_notification()

        self.assertEqual(mock_log.info.call_args_list[-1].args[0], "Next Google Home notification is scheduled for %s (in %d minute(s)).")
        self.assertEqual(mock_log.info.call_args_list[-1].args[1], future_soon.strftime("%Y-%m-%d %H:%M:%S %Z"))
        self.assertEqual(mock_log.info.call_args_list[-1].args[2], 3)

    @patch("src.monitor.log")
    @patch("src.monitor.scheduler")
    def test_log_next_notification_logs_when_none(self, mock_scheduler, mock_log):
        """Logs when no future Google Home notification is available."""
        from src.monitor import _log_next_notification
        from src.notify import notify_google_home

        fixed_now = datetime(2026, 4, 20, 5, 0, 0)
        past_job = MagicMock(func=notify_google_home, next_run_time=fixed_now - timedelta(minutes=1))
        mock_scheduler.get_jobs.return_value = [past_job]

        with patch("src.monitor.datetime") as mock_datetime:
            mock_datetime.now.return_value = fixed_now
            _log_next_notification()

        mock_log.info.assert_called_with("No upcoming Google Home notifications are currently scheduled.")

    @patch("src.monitor._log_next_notification")
    @patch("src.monitor.plan_day")
    @patch("src.monitor.scheduler")
    def test_start_scheduler_before_14_plans_today_only(self, mock_scheduler, mock_plan_day, mock_next_log):
        """Before 14:00, startup plans today only."""
        from src.monitor import start_scheduler

        with patch("src.monitor.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 20, 10, 0, 0)
            start_scheduler()

        mock_scheduler.start.assert_called_once()
        mock_plan_day.assert_called_once_with(date(2026, 4, 20), force_summary=True)
        mock_next_log.assert_called_once()

    @patch("src.monitor._log_next_notification")
    @patch("src.monitor.plan_day")
    @patch("src.monitor.scheduler")
    def test_start_scheduler_after_14_plans_today_and_tomorrow(self, mock_scheduler, mock_plan_day, mock_next_log):
        """After 14:00, startup also plans tomorrow (daily cron already fired)."""
        from src.monitor import start_scheduler

        with patch("src.monitor.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2026, 4, 20, 15, 0, 0)
            start_scheduler()

        mock_scheduler.start.assert_called_once()
        self.assertEqual(mock_plan_day.call_count, 2)
        self.assertEqual(mock_plan_day.call_args_list[0], call(date(2026, 4, 20), force_summary=True))
        self.assertEqual(mock_plan_day.call_args_list[1], call(date(2026, 4, 21)))
        mock_next_log.assert_called_once()

if __name__ == "__main__":
    unittest.main()
