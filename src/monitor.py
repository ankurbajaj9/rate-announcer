#!/usr/bin/env python3
"""
Stockholm Electricity Price Monitor — Telinet kvartspris edition
=================================================================
Scheduling orchestration: plans each day's price alerts and starts
the background scheduler.
"""

import logging
from datetime import date, datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from src.config import (
    QUIET_HOURS_END,
    QUIET_HOURS_START,
    SUMMARY_ANNOUNCE_DELAY_SEC,
    ALERT_OFFSET_MINUTES,
    THRESHOLD_PERCENT,
    NOTIFICATION_COOLDOWN_SEC,
)
from src.notify import notify_google_home, notify_play_sound
from src.prices import eur_mwh_to_sek_kwh, fetch_quarter_prices, get_eur_to_sek
from src.events import get_announced_drop_times

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
    high_price, high_time = high
    low_price, low_time = low
    # Shortened summary: compact, easy for TTS to speak quickly
    return (
        f"Summary for {day_word}: avg {avg_ore} öre; "
        f"max {high_price} öre at {high_time}; min {low_price} öre at {low_time}."
    )


def _build_alert_message(price_ore: float, pct: float, drop_time: datetime | None) -> str:
    """Return the high-price alert announcement text."""
    msg = f"Price alert: {price_ore} öre ({pct:.0f}% of max)."
    if drop_time:
        msg += f" Drops at {drop_time.strftime('%H:%M')}."
    else:
        msg += " No drop expected today."
    return msg


def _find_drop_time(prices_sek, threshold: float, from_index: int) -> datetime | None:
    """Return the first timestamp after *from_index* where the price drops below *threshold*."""
    for j in range(from_index, len(prices_sek)):
        if prices_sek.iloc[j] < threshold:
            return prices_sek.index[j].to_pydatetime()
    return None


def _log_next_notification() -> None:
    """Log when the next Google Home notification is scheduled."""
    now_ts = datetime.now().timestamp()
    upcoming_runs = [
        run_time
        for job in scheduler.get_jobs()
        if job.func == notify_google_home
        for run_time in [job.next_run_time]
        if run_time and run_time.timestamp() > now_ts
    ]

    if not upcoming_runs:
        log.info("No upcoming Google Home notifications are currently scheduled.")
        return

    next_run = min(upcoming_runs, key=lambda dt: dt.timestamp())
    minutes_until = int((next_run.timestamp() - now_ts) // 60)
    log.info(
        "Next Google Home notification is scheduled for %s (in %d minute(s)).",
        next_run.strftime("%Y-%m-%d %H:%M:%S %Z"),
        minutes_until,
    )


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
        high_time = prices_sek.idxmax().strftime("%H:%M")
        low_time = prices_sek.idxmin().strftime("%H:%M")
        high = (round(daily_max_sek * 100, 1), high_time)
        low = (round(daily_min_sek * 100, 1), low_time)
        threshold = daily_max_sek * THRESHOLD_PERCENT
        slot_delta = (
            prices_sek.index[1].to_pydatetime() - prices_sek.index[0].to_pydatetime()
            if len(prices_sek) > 1
            else timedelta(minutes=15)
        )

        log.info(
            "Planning for %s | Max SEK: %.4f | Threshold (%.0f%%): %.4f",
            target_date,
            daily_max_sek,
            THRESHOLD_PERCENT * 100,
            threshold,
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
            # Prevent duplicate summary jobs when restarting quickly
            run_summary_at = datetime.now() + timedelta(seconds=SUMMARY_ANNOUNCE_DELAY_SEC)
            duplicate = False
            for job in scheduler.get_jobs():
                if getattr(job, "func", None) == notify_google_home and job.next_run_time:
                    try:
                        # Compare next_run_time timestamps to avoid timezone issues
                        if abs(job.next_run_time.timestamp() - run_summary_at.timestamp()) < 2:
                            duplicate = True
                            break
                        # also check identical message args
                        if getattr(job, "args", None) and job.args and job.args[0] == summary_msg:
                            duplicate = True
                            break
                    except Exception:
                        continue
            if not duplicate:
                scheduler.add_job(
                    notify_google_home,
                    "date",
                    run_date=run_summary_at,
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
            # Schedule ALERT_OFFSET_MINUTES before the high-price timeslot
            scheduled_time = interval_time - timedelta(minutes=ALERT_OFFSET_MINUTES)
            current_time = datetime.now(scheduled_time.tzinfo)
            drop_time = _find_drop_time(prices_sek, threshold, i + 1)
            peak_end = drop_time or (prices_sek.index[-1].to_pydatetime() + slot_delta)

            if current_time >= peak_end:
                continue

            # If the service restarts after the alert time but the peak period
            # is still active, announce immediately instead of dropping it.
            run_date = scheduled_time
            if scheduled_time <= current_time:
                run_date = current_time

            # Skip future alerts if their playback time falls in quiet hours.
            if run_date == scheduled_time and is_quiet_hour(scheduled_time):
                continue
            pct = (current_sek / daily_max_sek) * 100
            price_ore = round(current_sek * 100, 1)
            msg = _build_alert_message(price_ore, pct, drop_time)
            log.info(
                "Scheduling notification for %.4f SEK (%.0f%%) at %s (play at %s). Drop time: %s",
                current_sek,
                pct,
                interval_time,
                run_date,
                drop_time,
            )

            # Deduplicate and check cooldown: skip scheduling if similar job exists or is too soon
            skip = False
            try:
                announced = get_announced_drop_times()
            except Exception:
                announced = []

            now = datetime.now()
            now_utc_ts = datetime.now(timezone.utc).timestamp()

            # Check for cooldown (if not overridden by job) and check identical message
            for job in scheduler.get_jobs():
                if getattr(job, "func", None) != notify_google_home or not job.next_run_time:
                    continue
                try:
                    job_ts = job.next_run_time.timestamp()
                    # Check cooldown period: is the run too soon after a previous run?
                    if 0 <= (now.timestamp() - job_ts) < NOTIFICATION_COOLDOWN_SEC:
                        skip = True
                        log.info("Skipping alert due to active cooldown.")
                        break
                except Exception:
                    pass

                # check identical message
                try:
                    if getattr(job, "args", None) and job.args and job.args[0] == msg:
                        skip = True
                        log.info("Skipping alert due to identical message.")
                        break
                except Exception:
                    pass

            # Check event log for success cooldown
            drop_time_iso = drop_time.isoformat() if drop_time else None
            for event in announced:
                if drop_time_iso and event.get('drop_time_iso') == drop_time_iso and event.get('success'):
                    # Check time since last successful announcement with this same key property (i.e., dropped at the same time)
                    event_ts = datetime.fromisoformat(event['ts'].replace("Z", "+00:00"))
                    event_ts_val = event_ts.timestamp() if event_ts.tzinfo else event_ts.timestamp()
                    if 0 <= (now_utc_ts - event_ts_val) < NOTIFICATION_COOLDOWN_SEC:
                        skip = True
                        log.info("Skipping alert due to recent successful announcement for this drop time.")
                        break


            if not skip:
                scheduler.add_job(
                    notify_google_home,
                    "date",
                    run_date=run_date,
                    args=[msg],
                    kwargs={"drop_time_iso": drop_time.isoformat() if drop_time else None},
                )

            # Schedule minor notification when peak period ends
            try:
                end_run_date = peak_end
                if end_run_date and end_run_date > current_time and not is_quiet_hour(end_run_date):
                    scheduler.add_job(
                        notify_play_sound,
                        "date",
                        run_date=end_run_date,
                        args=[],
                    )
            except Exception:
                log.exception("Failed scheduling end-of-peak sound for %s.", interval_time)

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
    4. If started after 14:00, also plan tomorrow — the cron has already fired
       for today and won't run again until tomorrow, so tomorrow's prices would
       otherwise be missing until then (e.g. after a post-14:00 reboot).
    """
    scheduler.add_job(daily_planner_job, "cron", hour=14, minute=0)
    scheduler.start()
    log.info("Scheduler started. Background monitoring active.")

    now = datetime.now()
    today = now.date()

    plan_day(today, force_summary=True)

    if now.hour >= 14:
        log.info(
            "Started after 14:00 — planning tomorrow's prices now "
            "(daily cron already fired for today)."
        )
        plan_day(today + timedelta(days=1))

    _log_next_notification()
    return scheduler
