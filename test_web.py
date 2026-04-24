"""
Unit tests for the web UI module (src/web.py).

Covers:
- _build_price_rows(): current-slot detection, level/threshold classification
- _next_announcement(): job filtering, countdown label formatting
"""

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pandas as pd

from src.web import _build_price_rows, _next_announcement, set_scheduler


class TestBuildPriceRows(unittest.TestCase):
    """Tests for _build_price_rows()."""

    def _make_series(self, values, start="2026-04-24 00:00", freq="15min", tz="Europe/Stockholm"):
        idx = pd.date_range(start, periods=len(values), freq=freq, tz=tz)
        return pd.Series(values, index=idx)

    def test_returns_empty_list_for_empty_series(self):
        self.assertEqual(_build_price_rows(pd.Series([], dtype=float)), [])

    def test_row_count_matches_series_length(self):
        prices = self._make_series([0.5, 0.6, 0.7, 0.8])
        rows = _build_price_rows(prices)
        self.assertEqual(len(rows), 4)

    def test_high_level_above_threshold(self):
        """Prices at or above 75 % of the daily max are classified as 'high'."""
        # daily max = 1.0, threshold = 0.75 → only 1.0 is high
        prices = self._make_series([0.3, 0.5, 1.0])
        rows = _build_price_rows(prices)
        self.assertEqual(rows[2]["level"], "high")

    def test_low_level_in_bottom_third(self):
        """Prices in the bottom 33 % of the range are classified as 'low'."""
        # range = 1.0 - 0.1 = 0.9, low boundary = 0.1 + 0.9*0.33 ≈ 0.397
        prices = self._make_series([0.1, 0.5, 1.0])
        rows = _build_price_rows(prices)
        self.assertEqual(rows[0]["level"], "low")

    def test_mid_level_in_middle(self):
        """Prices in the middle band are classified as 'mid'."""
        prices = self._make_series([0.1, 0.5, 1.0])
        rows = _build_price_rows(prices)
        self.assertEqual(rows[1]["level"], "mid")

    def test_current_slot_detected(self):
        """Exactly one row should have is_current=True for the live 15-min slot."""
        now_aware = pd.Timestamp.now(tz="Europe/Stockholm").floor("15min")
        start = now_aware - pd.Timedelta(minutes=15)
        idx = pd.date_range(start, periods=3, freq="15min")
        prices = pd.Series([0.3, 0.5, 0.4], index=idx)
        rows = _build_price_rows(prices)
        current_rows = [r for r in rows if r["is_current"]]
        self.assertEqual(len(current_rows), 1)
        self.assertEqual(current_rows[0]["time"], now_aware.strftime("%H:%M"))

    def test_no_current_slot_when_all_past(self):
        """No row is current when all timestamps are in the past."""
        prices = self._make_series(
            [0.3, 0.5],
            start="2000-01-01 00:00",
        )
        rows = _build_price_rows(prices)
        self.assertFalse(any(r["is_current"] for r in rows))

    def test_price_converted_to_ore(self):
        """Price in the row dict should be öre/kWh (SEK × 100), rounded to 1 dp."""
        prices = self._make_series([0.8])
        rows = _build_price_rows(prices)
        self.assertAlmostEqual(rows[0]["price"], 80.0, places=1)

    def test_pct_field(self):
        """pct should be the price as a percentage of the daily max."""
        prices = self._make_series([0.5, 1.0])
        rows = _build_price_rows(prices)
        self.assertEqual(rows[0]["pct"], 50)
        self.assertEqual(rows[1]["pct"], 100)


class TestNextAnnouncement(unittest.TestCase):
    """Tests for _next_announcement()."""

    def setUp(self):
        """Reset the module-level scheduler to None before each test."""
        set_scheduler(None)

    def test_returns_none_when_no_scheduler(self):
        result = _next_announcement()
        self.assertEqual(result, (None, None))

    def test_returns_none_when_no_upcoming_jobs(self):
        mock_scheduler = MagicMock()
        mock_scheduler.get_jobs.return_value = []
        set_scheduler(mock_scheduler)

        result = _next_announcement()
        self.assertEqual(result, (None, None))

    def test_ignores_non_notify_jobs(self):
        from src.notify import notify_google_home

        mock_scheduler = MagicMock()
        other_job = MagicMock()
        other_job.func = MagicMock()  # not notify_google_home
        other_job.next_run_time = datetime.now(tz=timezone.utc) + timedelta(minutes=5)
        mock_scheduler.get_jobs.return_value = [other_job]
        set_scheduler(mock_scheduler)

        result = _next_announcement()
        self.assertEqual(result, (None, None))

    def test_returns_nearest_notify_job(self):
        from src.notify import notify_google_home

        mock_scheduler = MagicMock()
        now = datetime.now(tz=timezone.utc)
        # Use +30 s buffer so integer-division by 60 reliably yields the expected minute count
        soon = now + timedelta(minutes=5, seconds=30)
        later = now + timedelta(minutes=30, seconds=30)

        job_soon = MagicMock(func=notify_google_home, next_run_time=soon)
        job_later = MagicMock(func=notify_google_home, next_run_time=later)
        mock_scheduler.get_jobs.return_value = [job_later, job_soon]
        set_scheduler(mock_scheduler)

        time_label, until_label = _next_announcement()
        self.assertEqual(time_label, soon.strftime("%H:%M:%S"))
        self.assertIn("5", until_label)

    def test_countdown_minutes_label(self):
        from src.notify import notify_google_home

        mock_scheduler = MagicMock()
        now = datetime.now(tz=timezone.utc)
        future = now + timedelta(minutes=45, seconds=30)

        job = MagicMock(func=notify_google_home, next_run_time=future)
        mock_scheduler.get_jobs.return_value = [job]
        set_scheduler(mock_scheduler)

        _, until_label = _next_announcement()
        self.assertIn("45", until_label)
        self.assertIn("min", until_label)

    def test_countdown_hours_label(self):
        from src.notify import notify_google_home

        mock_scheduler = MagicMock()
        now = datetime.now(tz=timezone.utc)
        future = now + timedelta(hours=2, minutes=30, seconds=30)

        job = MagicMock(func=notify_google_home, next_run_time=future)
        mock_scheduler.get_jobs.return_value = [job]
        set_scheduler(mock_scheduler)

        _, until_label = _next_announcement()
        self.assertIn("2h", until_label)
        self.assertIn("30", until_label)

    def test_countdown_exact_hours_label(self):
        from src.notify import notify_google_home

        mock_scheduler = MagicMock()
        now = datetime.now(tz=timezone.utc)
        future = now + timedelta(hours=3, seconds=30)

        job = MagicMock(func=notify_google_home, next_run_time=future)
        mock_scheduler.get_jobs.return_value = [job]
        set_scheduler(mock_scheduler)

        _, until_label = _next_announcement()
        self.assertEqual(until_label, "in 3h")

    def test_past_jobs_are_excluded(self):
        from src.notify import notify_google_home

        mock_scheduler = MagicMock()
        now = datetime.now(tz=timezone.utc)
        past = now - timedelta(minutes=10)

        job = MagicMock(func=notify_google_home, next_run_time=past)
        mock_scheduler.get_jobs.return_value = [job]
        set_scheduler(mock_scheduler)

        result = _next_announcement()
        self.assertEqual(result, (None, None))


class TestLoadPrices(unittest.TestCase):
    """Tests for _load_prices() — date validation and EUR→SEK conversion."""

    def test_returns_none_when_no_cache_file(self):
        from src.web import _load_prices

        with patch("src.web.os.path.exists", return_value=False):
            self.assertIsNone(_load_prices())

    def test_returns_none_when_cache_date_is_stale(self):
        from datetime import date
        from src.web import _load_prices

        tz = "Europe/Stockholm"
        idx = pd.date_range("2020-01-01", periods=4, freq="15min", tz=tz)
        stale_series = pd.Series([100.0] * 4, index=idx)
        stale_cache = ("2020-01-01", stale_series)  # old date

        with patch("src.web.os.path.exists", return_value=True), \
             patch("src.web.pd.read_pickle", return_value=stale_cache):
            result = _load_prices()
        self.assertIsNone(result)

    def test_converts_eur_mwh_to_sek_kwh(self):
        from datetime import date
        from src.web import _load_prices

        today_str = date.today().isoformat()
        tz = "Europe/Stockholm"
        idx = pd.date_range(today_str, periods=4, freq="15min", tz=tz)
        eur_series = pd.Series([100.0] * 4, index=idx)  # 100 EUR/MWh
        cache = (today_str, eur_series)
        fx_rate = 11.0  # 100 * 11 / 1000 = 1.1 SEK/kWh

        with patch("src.web.os.path.exists", return_value=True), \
             patch("src.web.pd.read_pickle", return_value=cache), \
             patch("src.web.get_eur_to_sek", return_value=fx_rate):
            result = _load_prices()

        self.assertIsNotNone(result)
        self.assertAlmostEqual(float(result.iloc[0]), 1.1)


if __name__ == "__main__":
    unittest.main()
