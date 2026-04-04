import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
from datetime import date
from src.monitor import eur_mwh_to_sek_kwh, get_current_quarter_price, fetch_quarter_prices_today

class TestPriceMonitor(unittest.TestCase):

    def test_eur_mwh_to_sek_kwh(self):
        # 100 EUR/MWh at 11.0 SEK/EUR = 1100 SEK/MWh = 1.1 SEK/kWh
        self.assertAlmostEqual(eur_mwh_to_sek_kwh(100, 11.0), 1.1)
        self.assertAlmostEqual(eur_mwh_to_sek_kwh(0, 11.0), 0.0)
        self.assertAlmostEqual(eur_mwh_to_sek_kwh(200, 10.5), 2.1)

    def test_get_current_quarter_price(self):
        # Create a sample series with 15-min intervals
        times = pd.date_range("2026-03-26 00:00:00", periods=4, freq="15min", tz="UTC")
        prices = pd.Series([10.0, 20.0, 30.0, 40.0], index=times)

        # Mock pd.Timestamp.utcnow() to return a specific time
        with patch("pandas.Timestamp.utcnow") as mock_now:
            # Floor("15min") of 00:07 is 00:00
            mock_now.return_value = pd.Timestamp("2026-03-26 00:07:00", tz="UTC")
            price = get_current_quarter_price(prices)
            self.assertEqual(price, 10.0)

            # Floor("15min") of 00:15 is 00:15
            mock_now.return_value = pd.Timestamp("2026-03-26 00:15:00", tz="UTC")
            price = get_current_quarter_price(prices)
            self.assertEqual(price, 20.0)

    @patch("src.monitor.EntsoePandasClient")
    def test_fetch_quarter_prices_today(self, mock_client_class):
        # Setup mock client
        mock_client = MagicMock()
        mock_client_class.return_value = mock_client
        
        # Create hourly index
        tz = "Europe/Stockholm"
        today = pd.Timestamp(date.today(), tz=tz)
        times = pd.date_range(today, periods=2, freq="1h")
        mock_prices = pd.Series([100.0, 120.0], index=times)
        
        mock_client.query_day_ahead_prices.return_value = mock_prices
        
        # Execution
        result = fetch_quarter_prices_today()
        
        # Verification
        # Original 2 hourly points should become 5 points (00:00, 00:15, 00:30, 00:45, 01:00)
        # However, resample("15min").ffill() on 2 points (00:00 and 01:00) 
        # will create entries for 00:00, 00:15, 00:30, 00:45 and 01:00
        self.assertEqual(len(result), 5) 
        self.assertEqual(result.iloc[0], 100.0)
        self.assertEqual(result.iloc[1], 100.0)
        self.assertEqual(result.iloc[4], 120.0)

if __name__ == "__main__":
    unittest.main()
