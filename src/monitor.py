#!/usr/bin/env python3
"""
Stockholm Electricity Price Monitor — Telinet kvartspris edition
=================================================================
Scheduling orchestration: plans each day's price alerts and starts
the background scheduler.
"""

import logging
from datetime import date, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler

from src.config import (
    QUIET_HOURS_END,
    QUIET_HOURS_START,
    SUMMARY_ANNOUNCE_DELAY_SEC,
    THRESHOLD_PERCENT,
)
from src.notify import notify_google_home
from src.prices import eur_mwh_to_sek_kwh, fetch_quarter_prices, get_eur_to_sek

# Configure logging once for the whole application
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


# ── Time helpers ─────────────────────────────

def is_quiet_hour(dt: datetime) -> bool:
    """Return True if *dt* falls within the configured quiet hours."""
    h = dt.hour
    if QUIET_HOURS_START > QUIET_HOURS_END:
        return h >= QUIET_HOURS_START or h < QUIET_HOURS_END
    return QUIET_HOURS_START <= h < QUIET_HOURS_END


# ── Day planning ─────────────────────────────

def _build_summary_message(
    day_word: str,
    avg_ore: float,
    high: tuple[float, str],
    low: tuple[float, str],
) -> str:
    """Return the daily summary announcement text.

    Args:
        day_word: "today" or "tomorrow".
        avg_ore:  Average price in öre/kWh.
        high:     (price_ore, HH:MM) for the daily maximum.
        low:      (price_ore, HH:MM) for the daily minimum.
    """
    return (
        f"I have fetched the electricity rates for {day_word}. "
        f"The average price is {avg_ore} öre per kilowatt hour. "
        f"The maximum price will be {high[0]} öre at {high[1]}, "
        f"and the minimum will be {low[0]} öre at {low[1]}."
    )


def _build_alert_message(price_ore: float, pct: float, drop_time: datetime | None) -> str:
    """Return the high-price alert announcement text."""
    msg = (
        f"Electricity price alert. The current rate is {price_ore} öre, "
        f"which is {pct:.0f} percent of today's maximum price. "
    )
    if drop_time:
        msg += (
            f"The rate will drop below the threshold at {drop_time.strftime('%H:%M')}. "
            "Consider delaying energy usage until then."
        )
    else:
        msg += "The rate will remain high for the rest of the day. Consider reducing energy usage."
    return msg


def _find_drop_time(prices_sek, threshold: float, from_index: int) -> datetime | None:
    """Return the first timestamp after *from_index* where the price drops below *threshold*."""
    for j in range(from_index, len(prices_sek)):
        if prices_sek.iloc[j] < threshold:
            return prices_sek.index[j].to_pydatetime()
    return None


def plan_day(target_date: date, force_summary: bool = False) -> None:
    """
    Fetch prices and FX for *target_date*, then schedule notifications:
    - A daily summary outside quiet hours (always when *force_summary* is True,
      otherwise only when prices were just fetched for the first time today).
    - One-shot alerts at each transition into a high-price window.
    """
    try:
        prices_eur, is_new_fetch = fetch_quarter_prices(target_date)
        if prices_eur.empty:
            log.warning("No price data found for %s.", target_date)
            return

        fx = get_eur_to_sek(target_date)
        prices_sek = prices_eur.map(lambda v: eur_mwh_to_sek_kwh(float(v), fx))
        del prices_eur  # raw EUR series no longer needed; free the memory

        daily_max_sek = float(prices_sek.max())
        daily_min_sek = float(prices_sek.min())
        daily_avg_sek = float(prices_sek.mean())
        high = (round(daily_max_sek * 100, 1), prices_sek.idxmax().strftime("%H:%M"))
        low = (round(daily_min_sek * 100, 1), prices_sek.idxmin().strftime("%H:%M"))
        threshold = daily_max_sek * THRESHOLD_PERCENT

        log.info(
            "Planning for %s | Max SEK: %.4f | Threshold (%.0f%%): %.4f",
            target_date, daily_max_sek, THRESHOLD_PERCENT * 100, threshold,
        )

        # Announce the daily summary on startup (force_summary) or when rates are
        # newly fetched, provided it is not a quiet hour.
        if (force_summary or is_new_fetch) and not is_quiet_hour(datetime.now()):
            day_word = "today" if target_date == date.today() else "tomorrow"
            summary_msg = _build_summary_message(
                day_word,
                round(daily_avg_sek * 100, 1),
                high,
                low,
            )
            log.info("Scheduling daily summary notification: %s", summary_msg)
            scheduler.add_job(
                notify_google_home,
                "date",
                run_date=datetime.now() + timedelta(seconds=SUMMARY_ANNOUNCE_DELAY_SEC),
                args=[summary_msg],
            )

        # Schedule one-shot alerts at every transition into a high-price window
        for i in range(len(prices_sek)):
            current_sek = prices_sek.iloc[i]
            interval_time = prices_sek.index[i].to_pydatetime()

            is_entering_high = current_sek >= threshold and (
                i == 0 or prices_sek.iloc[i - 1] < threshold
            )

            if not is_entering_high:
                continue
            if is_quiet_hour(interval_time):
                continue
            if interval_time <= datetime.now(interval_time.tzinfo):
                continue

            drop_time = _find_drop_time(prices_sek, threshold, i + 1)
            pct = (current_sek / daily_max_sek) * 100
            price_ore = round(current_sek * 100, 1)
            msg = _build_alert_message(price_ore, pct, drop_time)

            log.info(
                "Scheduling notification for %.4f SEK (%.0f%%) at %s. Drop time: %s",
                current_sek, pct, interval_time, drop_time,
            )
            scheduler.add_job(
                notify_google_home,
                "date",
                run_date=interval_time,
                args=[msg],
            )

    except Exception:
        log.exception("Workflow error while planning day for %s.", target_date)


def daily_planner_job() -> None:
    """Scheduler callback — plan tomorrow's alerts."""
    plan_day(date.today() + timedelta(days=1))


# ── Scheduler entry point ────────────────────

def start_scheduler() -> BackgroundScheduler:
    """
    Bootstrap the application:
    1. Register a daily cron job to plan tomorrow at 14:00.
    2. Start the background scheduler.
    3. Plan today immediately and announce the daily summary regardless of cache.
    """
    scheduler.add_job(daily_planner_job, "cron", hour=14, minute=0)
    scheduler.start()
    log.info("Scheduler started. Background monitoring active.")

    plan_day(date.today(), force_summary=True)
    return scheduler

