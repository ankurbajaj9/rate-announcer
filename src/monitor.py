#!/usr/bin/env python3
"""
Stockholm Electricity Price Monitor — Telinet kvartspris edition
=================================================================
Fetches spot prices from ENTSO-E and announces a Google Home alert.
"""

import os
import sys
import time
import socket
import threading
import tempfile
import http.server
import logging
from datetime import date
from typing import Optional

import requests
from entsoe import EntsoePandasClient
import pandas as pd
import pychromecast
from gtts import gTTS

from src.config import (
    ENTSOE_API_TOKEN,
    GOOGLE_HOME_NAME,
    PRICE_AREA,
    THRESHOLD_PERCENT,
    NOTIFICATION_COOLDOWN_SEC,
    STATE_FILE,
    SERVE_PORT,
    TTS_LANGUAGE
)

# Configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────

def get_local_ip() -> str:
    """Determine the local IP address for the HTTP server."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Using a reliable public address to find our local outgoing interface
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def read_last_alert_time() -> float:
    """Read the timestamp of the last alert from the state file."""
    if not os.path.exists(STATE_FILE):
        return 0.0
    try:
        with open(STATE_FILE) as f:
            return float(f.read().strip())
    except (ValueError, OSError) as e:
        log.warning("Could not read state file: %s. Starting fresh.", e)
        return 0.0


def write_last_alert_time(ts: float) -> None:
    """Save the current alert timestamp to the state file."""
    try:
        with open(STATE_FILE, "w") as f:
            f.write(str(ts))
    except OSError as e:
        log.error("Could not write state file: %s", e)


# ── Price data fetching ──────────────────────

def fetch_quarter_prices_today() -> pd.Series:
    """
    Fetch today's 15-minute price granularity from ENTSO-E.
    Note: Some areas only publish hourly; we resample if needed.
    """
    client = EntsoePandasClient(api_key=ENTSOE_API_TOKEN)
    tz = "Europe/Stockholm"
    today = pd.Timestamp(date.today(), tz=tz)
    start = today
    end = today + pd.Timedelta(days=1)

    log.info("Fetching %s day-ahead prices from ENTSO-E (%s) ...", PRICE_AREA, today.date())
    prices = client.query_day_ahead_prices(PRICE_AREA, start=start, end=end)
    
    # Resample to 15-min and forward-fill if the source is hourly
    if isinstance(prices.index, pd.DatetimeIndex):
        return prices.resample("15min").ffill()
    return prices


def get_eur_to_sek() -> float:
    """Fetch live EUR/SEK exchange rate with fallback."""
    try:
        r = requests.get(
            "https://api.frankfurter.app/latest?from=EUR&to=SEK", timeout=10
        )
        r.raise_for_status()
        return r.json()["rates"]["SEK"]
    except Exception as e:
        log.warning("FX fetch failed (%s) — using fallback rate 11.0 SEK/EUR", e)
        return 11.0


def eur_mwh_to_sek_kwh(eur_mwh: float, fx: float) -> float:
    """Convert price from EUR/MWh to SEK/kWh."""
    return eur_mwh * fx / 1000


def get_current_quarter_price(prices: pd.Series) -> Optional[float]:
    """Retrieve the price for the current 15-minute time bucket."""
    now_utc = pd.Timestamp.utcnow().floor("15min")
    try:
        # Match current time precisely or find nearest previous
        return prices.asof(now_utc)
    except Exception:
        return None


# ── Notification ─────────────────────────────

class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """Silent HTTP handler to avoid terminal clutter."""
    def log_message(self, *_):
        pass


def _serve_file(filepath: str, port: int):
    """Start a temporary HTTP server for Chromecast access."""
    directory = os.path.dirname(filepath)
    filename = os.path.basename(filepath)

    class H(_QuietHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=directory, **kw)

    server = http.server.HTTPServer(("", port), H)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://{get_local_ip()}:{port}/{filename}"


def notify_google_home(message: str) -> bool:
    """Speak the message via Google Home using TTS and Chromecast."""
    log.info("Generating TTS audio ...")
    tts = gTTS(text=message, lang=TTS_LANGUAGE)
    
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tts.save(tmp.name)
        audio_path = tmp.name

    server, audio_url = _serve_file(audio_path, SERVE_PORT)
    log.info("Serving audio: %s", audio_url)

    browser = None
    try:
        log.info("Connecting to Google Home: '%s' ...", GOOGLE_HOME_NAME)
        chromecasts, browser = pychromecast.get_listed_chromecasts(
            friendly_names=[GOOGLE_HOME_NAME]
        )
        
        if not chromecasts:
            log.error("Google Home '%s' not found.", GOOGLE_HOME_NAME)
            return False

        cast = chromecasts[0]
        cast.wait()
        
        mc = cast.media_controller
        mc.play_media(audio_url, "audio/mp3")
        mc.block_until_active(timeout=30)
        
        # Estimate message duration
        wait_time = max(10, len(message) // 8)
        time.sleep(wait_time)
        return True

    except Exception as e:
        log.error("Notification failed: %s", e)
        return False
    finally:
        server.shutdown()
        if browser:
            browser.stop_discovery()
        if os.path.exists(audio_path):
            os.unlink(audio_path)


# ── Run logic ────────────────────────────────

def run():
    """Main execution cycle: check cooldown, fetch prices, and alert if needed."""
    # 1. Cooldown Check
    last_alert = read_last_alert_time()
    elapsed = time.time() - last_alert
    if elapsed < NOTIFICATION_COOLDOWN_SEC:
        remaining = int((NOTIFICATION_COOLDOWN_SEC - elapsed) // 60)
        log.info("Cooldown active: %d minutes remaining.", remaining)
        return

    # 2. Fetch prices
    try:
        prices_eur = fetch_quarter_prices_today()
        if prices_eur.empty:
            log.warning("No price data found.")
            return

        current_eur = get_current_quarter_price(prices_eur)
        if current_eur is None:
            log.warning("Could not find price for current 15-min window.")
            return

        fx = get_eur_to_sek()
        current_sek = eur_mwh_to_sek_kwh(float(current_eur), fx)
        daily_max_sek = eur_mwh_to_sek_kwh(float(prices_eur.max()), fx)
        threshold = daily_max_sek * THRESHOLD_PERCENT
        pct = (current_sek / daily_max_sek) * 100

        log.info(
            "Price: %.4f SEK/kWh | Max: %.4f | Threshold (%.0f%%): %.4f | Current: %.0f%% of max",
            current_sek, daily_max_sek, THRESHOLD_PERCENT * 100, threshold, pct
        )

        # 3. Decision
        if current_sek >= threshold:
            price_ore = round(current_sek * 100, 1)
            msg = (
                f"Electricity price alert. The current rate is {price_ore} öre, "
                f"which is {pct:.0f} percent of today's maximum price. "
                "Consider reducing energy usage."
            )
            log.info("ALARM! Sending notification...")
            if notify_google_home(msg):
                write_last_alert_time(time.time())
        else:
            log.info("Price is within safe limits. No action.")

    except Exception as e:
        log.exception("Workflow error: %s", e)


if __name__ == "__main__":
    run()
