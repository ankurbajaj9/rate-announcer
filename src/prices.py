"""
Price fetching, caching, and unit-conversion helpers.

Responsibilities:
- Fetch 15-minute day-ahead spot prices from ENTSO-E (with pickle cache)
- Fetch EUR/SEK exchange rate from Frankfurter (with JSON cache)
- Convert prices from EUR/MWh to SEK/kWh
"""

import json
import logging
import os
import requests
from datetime import date, timedelta
from typing import Any

import pandas as pd
from entsoe import EntsoePandasClient

from src.config import (
    ENTSOE_API_TOKEN,
    FX_CACHE_FILE,
    PRICE_AREA,
    PRICE_CACHE_FILE,
)

log = logging.getLogger(__name__)

_FX_FALLBACK_RATE = 11.0


def fetch_quarter_prices(target_date: date) -> tuple[Any, bool]:
    """
    Fetch a target date's 15-minute price granularity from ENTSO-E.
    Note: Some areas only publish hourly prices; those are resampled to 15 min.
    Returns a tuple of (prices, is_new_fetch).
    """
    target_date_str = target_date.isoformat()
    today, tomorrow = date.today(), date.today() + timedelta(days=1)

    if target_date in (today, tomorrow):
        if os.path.exists(PRICE_CACHE_FILE):
            try:
                cached_data = pd.read_pickle(PRICE_CACHE_FILE)
                if isinstance(cached_data, tuple) and len(cached_data) == 2:
                    cached_date, prices = cached_data
                    if cached_date == target_date_str:
                        return prices, False
            except Exception as e:
                log.warning("Failed to load price cache: %s", e)

    client = EntsoePandasClient(api_key=ENTSOE_API_TOKEN)
    tz = "Europe/Stockholm"
    start = pd.Timestamp(target_date, tz=tz)
    end = start + pd.Timedelta(days=1)

    log.info("Fetching %s day-ahead prices from ENTSO-E (%s) ...", PRICE_AREA, target_date)
    prices = client.query_day_ahead_prices(PRICE_AREA, start=start, end=end)

    # Resample to 15-min and forward-fill if the source is hourly
    if isinstance(prices.index, pd.DatetimeIndex):
        prices = prices.resample("15min").ffill()

    if target_date in (today, tomorrow):
        try:
            pd.to_pickle((target_date_str, prices), PRICE_CACHE_FILE)
        except Exception as e:
            log.warning("Failed to save price cache: %s", e)

    return prices, True


def get_eur_to_sek(target_date: date) -> float:
    """Fetch the live EUR/SEK exchange rate with fallback to a hardcoded default.

    The Frankfurter /latest endpoint always returns *today's* rate, so the
    cache is intentionally keyed on today's date only.  For any other
    target_date we still fetch live but skip the cache to avoid storing a
    rate under a future date and serving it as "fresh" the next day.
    """
    today = date.today()
    today_str = today.isoformat()

    if target_date == today:
        if os.path.exists(FX_CACHE_FILE):
            try:
                with open(FX_CACHE_FILE, "r") as f:
                    cached_data = json.load(f)
                if cached_data.get("date") == today_str:
                    rate = cached_data.get("rate")
                    if isinstance(rate, (int, float)):
                        return float(rate)
                    log.warning("Invalid rate in FX cache (%r) — refetching.", rate)
            except Exception as e:
                log.warning("Failed to load FX cache: %s", e)

    try:
        r = requests.get(
            "https://api.frankfurter.app/latest?from=EUR&to=SEK", timeout=10
        )
        r.raise_for_status()
        rate = r.json()["rates"]["SEK"]

        if target_date == today:
            try:
                with open(FX_CACHE_FILE, "w") as f:
                    json.dump({"date": today_str, "rate": rate}, f)
            except Exception as e:
                log.warning("Failed to save FX cache: %s", e)

        return rate
    except Exception as e:
        log.warning("FX fetch failed (%s) — using fallback rate %.1f SEK/EUR", e, _FX_FALLBACK_RATE)
        return _FX_FALLBACK_RATE


def eur_mwh_to_sek_kwh(eur_mwh: float, fx: float) -> float:
    """Convert a price from EUR/MWh to SEK/kWh."""
    return eur_mwh * fx / 1000
