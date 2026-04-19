#!/usr/bin/env python3
"""
Stockholm Electricity Price Monitor — Telinet kvartspris edition
=================================================================
Fetches spot prices from ENTSO-E and announces a Google Home alert.
Scheduled via BackgroundScheduler.
"""

import os
import time
import socket
import threading
import tempfile
import http.server
import logging
import json
import requests
from datetime import date, datetime, timedelta
from typing import Optional, Any

import zeroconf
import pychromecast
from gtts import gTTS
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger

from src.config import (
    ENTSOE_API_TOKEN,
    GOOGLE_HOME_NAME,
    PRICE_AREA,
    THRESHOLD_PERCENT,
    QUIET_HOURS_START,
    QUIET_HOURS_END,
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

scheduler = BackgroundScheduler()

# ── Helpers ──────────────────────────────────

def get_local_ip() -> str:
    """Determine the local IP address for the HTTP server."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def is_quiet_hour(dt: datetime) -> bool:
    """Check if the given datetime is within quiet hours."""
    h = dt.hour
    if QUIET_HOURS_START > QUIET_HOURS_END:
        return h >= QUIET_HOURS_START or h < QUIET_HOURS_END
    else:
        return QUIET_HOURS_START <= h < QUIET_HOURS_END


# ── Price data fetching ──────────────────────

def fetch_quarter_prices(target_date: date) -> tuple[Any, bool]:
    """
    Fetch a target date's 15-minute price granularity from ENTSO-E.
    Note: Some areas only publish hourly; we resample if needed.
    Returns: A tuple of (prices, is_new_fetch)
    """
    import pandas as pd
    from entsoe import EntsoePandasClient

    cache_file = "/tmp/rate_announcer_prices.pkl"
    target_date_str = target_date.isoformat()
    today, tomorrow = date.today(), date.today() + timedelta(days=1)

    if target_date in (today, tomorrow):
        if os.path.exists(cache_file):
            try:
                cached_data = pd.read_pickle(cache_file)
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
            pd.to_pickle((target_date_str, prices), cache_file)
        except Exception as e:
            log.warning("Failed to save price cache: %s", e)

    return prices, True


def get_eur_to_sek(target_date: date) -> float:
    """Fetch live EUR/SEK exchange rate with fallback."""
    cache_file = "/tmp/rate_announcer_fx.json"
    target_date_str = target_date.isoformat()
    today, tomorrow = date.today(), date.today() + timedelta(days=1)

    if target_date in (today, tomorrow):
        if os.path.exists(cache_file):
            try:
                with open(cache_file, "r") as f:
                    cached_data = json.load(f)
                if cached_data.get("date") == target_date_str:
                    return cached_data.get("rate")
            except Exception as e:
                log.warning("Failed to load FX cache: %s", e)

    try:
        r = requests.get(
            "https://api.frankfurter.app/latest?from=EUR&to=SEK", timeout=10
        )
        r.raise_for_status()
        rate = r.json()["rates"]["SEK"]

        if target_date in (today, tomorrow):
            try:
                with open(cache_file, "w") as f:
                    json.dump({"date": target_date_str, "rate": rate}, f)
            except Exception as e:
                log.warning("Failed to save FX cache: %s", e)

        return rate
    except Exception as e:
        log.warning("FX fetch failed (%s) — using fallback rate 11.0 SEK/EUR", e)
        return 11.0


def eur_mwh_to_sek_kwh(eur_mwh: float, fx: float) -> float:
    """Convert price from EUR/MWh to SEK/kWh."""
    return eur_mwh * fx / 1000


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
    zconf = None
    try:
        log.info("Connecting to Google Home: '%s' ...", GOOGLE_HOME_NAME)
        
        cast = None
        discover_complete = threading.Event()
        
        def add_callback(uuid, service):
            nonlocal cast
            cast_info = browser.devices[uuid]
            if cast_info.friendly_name == GOOGLE_HOME_NAME:
                cast = pychromecast.get_chromecast_from_cast_info(cast_info, zconf)
                discover_complete.set()

        zconf = zeroconf.Zeroconf()
        browser = pychromecast.discovery.CastBrowser(
            pychromecast.discovery.SimpleCastListener(add_callback=add_callback),
            zconf
        )
        browser.start_discovery()
        
        discover_complete.wait(timeout=10.0)
        
        if not cast:
            log.error("Google Home '%s' not found.", GOOGLE_HOME_NAME)
            return False

        cast.wait()
        
        mc = cast.media_controller
        mc.play_media(audio_url, "audio/mpeg", stream_type="BUFFERED")
        mc.block_until_active(timeout=30)

        playback_ready = False
        for _ in range(20):  # up to 10 seconds
            mc.update_status()
            status = getattr(mc, "status", None)
            state = getattr(status, "player_state", None)
            idle_reason = getattr(status, "idle_reason", None)

            if state in {"PLAYING", "BUFFERING", "PAUSED"}:
                playback_ready = True
                break
            if state == "IDLE" and idle_reason in {"ERROR", "CANCELLED", "INTERRUPTED"}:
                break
            time.sleep(0.5)

        if not playback_ready:
            log.error("Chromecast did not start playback for '%s'.", GOOGLE_HOME_NAME)
            return False
        
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
        if zconf:
            zconf.close()
        if os.path.exists(audio_path):
            os.unlink(audio_path)


# ── Scheduling logic ────────────────────────

def plan_day(target_date: date):
    """
    Fetches prices/FX for a target date, scans all 15-min intervals,
    and schedules immediate jobs if price >= threshold and outside quiet hours.
    """
    import pandas as pd
    try:
        prices_eur, is_new_fetch = fetch_quarter_prices(target_date)
        if prices_eur.empty:
            log.warning("No price data found for %s.", target_date)
            return

        fx = get_eur_to_sek(target_date)
        daily_max_sek = eur_mwh_to_sek_kwh(float(prices_eur.max()), fx)
        daily_min_sek = eur_mwh_to_sek_kwh(float(prices_eur.min()), fx)
        daily_avg_sek = eur_mwh_to_sek_kwh(float(prices_eur.mean()), fx)
        threshold = daily_max_sek * THRESHOLD_PERCENT

        log.info("Planning for %s | Max SEK: %.4f | Threshold (%.0f%%): %.4f",
                 target_date, daily_max_sek, THRESHOLD_PERCENT * 100, threshold)

        # Let the user know the summary if the rates were just fetched
        if is_new_fetch and not is_quiet_hour(datetime.now()):
            day_word = "today" if target_date == date.today() else "tomorrow"
            
            # Announce the summary right away using the scheduler
            max_ore = round(daily_max_sek * 100, 1)
            min_ore = round(daily_min_sek * 100, 1)
            avg_ore = round(daily_avg_sek * 100, 1)
            
            summary_msg = (
                f"I have fetched the electricity rates for {day_word}. "
                f"The average price is {avg_ore} öre per kilowatt hour. "
                f"The maximum price will be {max_ore} öre, and the minimum will be {min_ore} öre."
            )
            log.info("Scheduling daily summary notification: %s", summary_msg)
            scheduler.add_job(
                notify_google_home,
                'date',
                run_date=datetime.now() + timedelta(seconds=2),
                args=[summary_msg]
            )

        for i in range(len(prices_eur)):
            ts = prices_eur.index[i]
            eur_price = prices_eur.iloc[i]
            current_sek = eur_mwh_to_sek_kwh(float(eur_price), fx)
            
            # Use interval's start time for notification
            interval_time = ts.to_pydatetime()
            is_high = current_sek >= threshold
            
            # Check if this is the start of a high price period
            is_entering_high = False
            if is_high:
                if i == 0:
                    is_entering_high = True
                else:
                    prev_eur_price = prices_eur.iloc[i - 1]
                    prev_sek = eur_mwh_to_sek_kwh(float(prev_eur_price), fx)
                    if prev_sek < threshold:
                        is_entering_high = True

            if is_entering_high:
                # Find when the price drops back below the threshold
                drop_time = None
                for j in range(i + 1, len(prices_eur)):
                    future_sek = eur_mwh_to_sek_kwh(float(prices_eur.iloc[j]), fx)
                    if future_sek < threshold:
                        drop_time = prices_eur.index[j].to_pydatetime()
                        break

                if not is_quiet_hour(interval_time):
                    # Only schedule if the run_date is strictly in the future
                    if interval_time > datetime.now(interval_time.tzinfo):
                        pct = (current_sek / daily_max_sek) * 100
                        price_ore = round(current_sek * 100, 1)
                        
                        msg = (
                            f"Electricity price alert. The current rate is {price_ore} öre, "
                            f"which is {pct:.0f} percent of today's maximum price. "
                        )
                        
                        if drop_time:
                            drop_time_str = drop_time.strftime("%H:%M")
                            msg += f"The rate will drop below the threshold at {drop_time_str}. Consider delaying energy usage until then."
                        else:
                            msg += "The rate will remain high for the rest of the day. Consider reducing energy usage."
                        
                        log.info("Scheduling notification for %.4f SEK (%.0f%%) at %s. Drop time: %s", 
                                 current_sek, pct, interval_time, drop_time)
                                 
                        scheduler.add_job(
                            notify_google_home,
                            'date',
                            run_date=interval_time,
                            args=[msg]
                        )
    except Exception as e:
        log.exception("Workflow error while planning day: %s", e)


def daily_planner_job():
    """Simply calls plan_day for tomorrow."""
    tomorrow = date.today() + timedelta(days=1)
    plan_day(tomorrow)


def start_scheduler() -> BackgroundScheduler:
    """Configures and starts the scheduler for daily price checks."""
    # Plan current day immediately to pick up any remaining peaks for today
    plan_day(date.today())

    # Schedule the planning for tomorrow at 14:00 daily
    scheduler.add_job(
        daily_planner_job,
        'cron',
        hour=14,
        minute=0
    )

    scheduler.start()
    log.info("Scheduler started. Background monitoring active.")
    return scheduler
