import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from src.config import EVENTS_DB_FILE

_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    event TEXT NOT NULL,
    success INTEGER NOT NULL,
    message TEXT,
    drop_time_iso TEXT
);
"""


def _get_conn():
    conn = sqlite3.connect(EVENTS_DB_FILE, detect_types=sqlite3.PARSE_DECLTYPES)
    return conn


def init_db() -> None:
    with _lock:
        conn = _get_conn()
        try:
            cur = conn.cursor()
            cur.executescript(SCHEMA)
            conn.commit()
        finally:
            conn.close()


def record_event(event: str, success: bool, message: Optional[str] = None, drop_time_iso: Optional[str] = None) -> None:
    init_db()
    with _lock:
        conn = _get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO events (ts, event, success, message, drop_time_iso) VALUES (?, ?, ?, ?, ?)",
                (datetime.now(timezone.utc).isoformat(), event, 1 if success else 0, message, drop_time_iso),
            )
            conn.commit()
        finally:
            conn.close()


def get_announced_drop_times() -> List[Dict[str, Any]]:
    """Return list of event dicts for notify_google_home events."""
    init_db()
    out: List[Dict[str, Any]] = []
    with _lock:
        conn = _get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT ts, success, drop_time_iso FROM events WHERE event = ? AND drop_time_iso IS NOT NULL",
                ("notify_google_home",),
            )
            rows = cur.fetchall()
            for ts, success, dt in rows:
                out.append({
                    "ts": ts,
                    "success": bool(success),
                    "drop_time_iso": dt,
                })
        finally:
            conn.close()
    return out

