"""Persistent runtime setting for Google Home notifications."""

import logging
import os
import tempfile

from src.config import ENABLE_NOTIFICATIONS, STATE_FILE

log = logging.getLogger(__name__)


def notifications_enabled() -> bool:
    """Read the UI override, falling back to the configured default."""
    try:
        with open(STATE_FILE, encoding="utf-8") as state:
            value = state.read().strip()
    except FileNotFoundError:
        return ENABLE_NOTIFICATIONS
    except OSError:
        log.exception("Unable to read notification setting; disabling notifications.")
        return False

    if value not in ("true", "false"):
        log.error("Invalid notification setting; disabling notifications.")
        return False
    return value == "true"


def set_notifications_enabled(enabled: bool) -> None:
    """Atomically persist the setting so scheduled jobs see it on execution."""
    path = os.path.abspath(STATE_FILE)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=os.path.dirname(path), delete=False
        ) as state:
            temp_path = state.name
            state.write("true" if enabled else "false")
        os.replace(temp_path, path)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)
