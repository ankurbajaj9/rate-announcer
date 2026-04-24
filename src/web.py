"""
Web UI for the Rate Announcer.

Serves a dashboard at http://<host>:<WEB_PORT>/ that shows:
- Today's 15-minute electricity prices
- The current price interval highlighted
- The next scheduled Google Home announcement
"""

import logging
import os
import threading
from datetime import datetime, timezone

import pandas as pd
from flask import Flask, jsonify, render_template

from src.config import (
    PRICE_AREA,
    PRICE_CACHE_FILE,
    THRESHOLD_PERCENT,
    WEB_PORT,
)

log = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates")

# Injected by main.py after the scheduler is started
_scheduler = None


def set_scheduler(scheduler) -> None:
    """Register the APScheduler instance so the web layer can query it."""
    global _scheduler
    _scheduler = scheduler


# ── Data helpers ─────────────────────────────────────────────────────────────

def _load_prices() -> pd.Series | None:
    """Load today's price series (SEK/kWh) from cache, or return None."""
    if not os.path.exists(PRICE_CACHE_FILE):
        return None
    try:
        cached = pd.read_pickle(PRICE_CACHE_FILE)
        if isinstance(cached, tuple) and len(cached) == 2:
            _, prices = cached
            if isinstance(prices, pd.Series):
                return prices
    except Exception as exc:
        log.warning("web: failed to load price cache: %s", exc)
    return None


def _next_announcement() -> tuple[str | None, str | None]:
    """
    Return (formatted_time, time_until_label) for the next Google Home
    notification, or (None, None) if nothing is scheduled.
    """
    if _scheduler is None:
        return None, None

    from src.notify import notify_google_home  # local import to avoid circular dep

    now_ts = datetime.now().timestamp()
    upcoming = [
        job.next_run_time
        for job in _scheduler.get_jobs()
        if job.func == notify_google_home
        and job.next_run_time
        and job.next_run_time.timestamp() > now_ts
    ]
    if not upcoming:
        return None, None

    next_dt = min(upcoming, key=lambda d: d.timestamp())
    minutes = int((next_dt.timestamp() - now_ts) // 60)
    time_label = next_dt.strftime("%H:%M:%S")
    if minutes < 60:
        until_label = f"in {minutes} min"
    else:
        hours = minutes // 60
        mins = minutes % 60
        until_label = f"in {hours}h {mins}m" if mins else f"in {hours}h"
    return time_label, until_label


def _build_price_rows(prices: pd.Series) -> list[dict]:
    """Convert a SEK/kWh price Series into a list of template-ready dicts."""
    if prices.empty:
        return []

    now = datetime.now(tz=prices.index[0].tzinfo)
    daily_max = float(prices.max())
    daily_min = float(prices.min())
    price_range = daily_max - daily_min if daily_max != daily_min else 1.0
    threshold = daily_max * THRESHOLD_PERCENT

    rows = []
    for ts, val in prices.items():
        price_sek = float(val)
        price_ore = round(price_sek * 100, 1)
        pct = round((price_sek / daily_max) * 100) if daily_max else 0

        # Colour band (high / mid / low)
        if price_sek >= threshold:
            level, level_label, bar_color = "high", "High", "#ef4444"
        elif price_sek <= daily_min + price_range * 0.33:
            level, level_label, bar_color = "low", "Low", "#22c55e"
        else:
            level, level_label, bar_color = "mid", "Mid", "#f59e0b"

        # Is this the currently active 15-min slot?
        ts_dt = ts.to_pydatetime() if hasattr(ts, "to_pydatetime") else ts
        is_current = ts_dt <= now < ts_dt + pd.Timedelta(minutes=15)

        rows.append(
            {
                "time": ts_dt.strftime("%H:%M"),
                "price": price_ore,
                "pct": pct,
                "level": level,
                "level_label": level_label,
                "bar_color": bar_color,
                "is_current": is_current,
            }
        )
    return rows


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    """Render the HTML price dashboard."""
    prices = _load_prices()
    price_rows = _build_price_rows(prices) if prices is not None else []

    # Summary stats
    if prices is not None and not prices.empty:
        avg_price = round(float(prices.mean()) * 100, 1)
        low_price = round(float(prices.min()) * 100, 1)
        high_price = round(float(prices.max()) * 100, 1)
    else:
        avg_price = low_price = high_price = "—"

    # Current price
    current_row = next((r for r in price_rows if r["is_current"]), None)
    current_price = current_row["price"] if current_row else "—"
    current_time = current_row["time"] if current_row else "—"

    next_alert, next_alert_in = _next_announcement()

    return render_template(
        "index.html",
        price_area=PRICE_AREA,
        prices=price_rows,
        avg_price=avg_price,
        low_price=low_price,
        high_price=high_price,
        current_price=current_price,
        current_time=current_time,
        next_alert=next_alert,
        next_alert_in=next_alert_in,
        date_label=datetime.now().strftime("%A, %d %b %Y"),
        generated_at=datetime.now().strftime("%H:%M:%S"),
    )


@app.route("/api/status")
def api_status():
    """JSON status endpoint — machine-readable version of the dashboard."""
    prices = _load_prices()
    price_rows = _build_price_rows(prices) if prices is not None else []

    if prices is not None and not prices.empty:
        avg_price = round(float(prices.mean()) * 100, 1)
        low_price = round(float(prices.min()) * 100, 1)
        high_price = round(float(prices.max()) * 100, 1)
    else:
        avg_price = low_price = high_price = None

    current_row = next((r for r in price_rows if r["is_current"]), None)
    next_alert, next_alert_in = _next_announcement()

    return jsonify(
        {
            "price_area": PRICE_AREA,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "current_price_ore": current_row["price"] if current_row else None,
            "current_slot": current_row["time"] if current_row else None,
            "avg_price_ore": avg_price,
            "low_price_ore": low_price,
            "high_price_ore": high_price,
            "next_announcement": next_alert,
            "next_announcement_in": next_alert_in,
            "prices": [
                {"time": r["time"], "price_ore": r["price"], "level": r["level"]}
                for r in price_rows
            ],
        }
    )


# ── Server bootstrap ──────────────────────────────────────────────────────────

def start_web_server() -> None:
    """Start the Flask development server in a background daemon thread."""
    thread = threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=WEB_PORT, use_reloader=False),
        daemon=True,
        name="web-ui",
    )
    thread.start()
    log.info("Web UI available at http://0.0.0.0:%d/", WEB_PORT)
