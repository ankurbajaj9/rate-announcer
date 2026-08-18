import os
from dotenv import load_dotenv

load_dotenv()

# ENTSO-E API Configuration
ENTSOE_API_TOKEN = os.getenv("ENTSOE_API_TOKEN", "YOUR_ENTSOE_TOKEN_HERE")
PRICE_AREA = os.getenv("PRICE_AREA", "SE_3")

# Google Home Configuration
GOOGLE_HOME_NAME = os.getenv("GOOGLE_HOME_NAME", "Your Google Home Name")
# Optional: set to the device's static IP to bypass mDNS discovery entirely.
# Strongly recommended for production deployments to avoid mDNS timeouts and
# Zeroconf reconnect errors.
GOOGLE_HOME_HOST = os.getenv("GOOGLE_HOME_HOST", "")
GOOGLE_HOME_PORT = int(os.getenv("GOOGLE_HOME_PORT", "8009"))
TTS_LANGUAGE = os.getenv("TTS_LANGUAGE", "en")

# Threshold and Alert Configuration
THRESHOLD_PERCENT = float(os.getenv("THRESHOLD_PERCENT", "0.75"))
# Reserved for future cooldown / deduplication logic
NOTIFICATION_COOLDOWN_SEC = int(os.getenv("NOTIFICATION_COOLDOWN_SEC", "3600"))
# Reserved for future announcement windowing logic
ANNOUNCE_MINUTE_WINDOW = int(os.getenv("ANNOUNCE_MINUTE_WINDOW", "5"))

# Quiet Hours Configuration (24-hour format)
QUIET_HOURS_START = int(os.getenv("QUIET_HOURS_START", "22"))
QUIET_HOURS_END = int(os.getenv("QUIET_HOURS_END", "7"))

# Service Configuration
SERVE_PORT = int(os.getenv("SERVE_PORT", "8765"))
# Reserved for future persistent state storage
STATE_FILE = os.getenv("STATE_FILE", "/tmp/price_monitor_state")

# Cache file paths
PRICE_CACHE_FILE = os.getenv("PRICE_CACHE_FILE", "/tmp/rate_announcer_prices.pkl")
FX_CACHE_FILE = os.getenv("FX_CACHE_FILE", "/tmp/rate_announcer_fx.json")

# Events log file (append-only JSON lines) to record notifications and actions.
# This is separate from STATE_FILE which may be used for compact state.
EVENTS_DB_FILE = os.getenv("EVENTS_DB_FILE", "/tmp/rate_announcer_events.db")

# Scheduling
SUMMARY_ANNOUNCE_DELAY_SEC = int(os.getenv("SUMMARY_ANNOUNCE_DELAY_SEC", "2"))
# How many minutes before a high-price timeslot to play the alert.
# Set via environment variable `ALERT_OFFSET_MINUTES`. Default: 1 minute.
ALERT_OFFSET_MINUTES = int(os.getenv("ALERT_OFFSET_MINUTES", "1"))
PLANNER_CRON_HOUR = int(os.getenv("PLANNER_CRON_HOUR", "14"))
PLANNER_CRON_MINUTE = int(os.getenv("PLANNER_CRON_MINUTE", "0"))

# Web UI
WEB_PORT = int(os.getenv("WEB_PORT", "8080"))
WEB_HOST = os.getenv("WEB_HOST", "0.0.0.0")

# Enable or disable sending notifications (Google Home TTS / sound).
# Recognize truthy values: 1, true, yes, on (case-insensitive). Default: enabled.
ENABLE_NOTIFICATIONS = os.getenv("ENABLE_NOTIFICATIONS", "true").lower() in (
	"1",
	"true",
	"yes",
	"on",
)

# Notification runtime tuning
DISCOVERY_TIMEOUT_SEC = float(os.getenv("DISCOVERY_TIMEOUT_SEC", "10"))
MEDIA_START_TIMEOUT_SEC = int(os.getenv("MEDIA_START_TIMEOUT_SEC", "30"))
PLAYBACK_CHECK_INTERVAL_SEC = float(os.getenv("PLAYBACK_CHECK_INTERVAL_SEC", "0.5"))
MAX_PLAYBACK_CHECK_ATTEMPTS = int(os.getenv("MAX_PLAYBACK_CHECK_ATTEMPTS", "20"))

# Price fetch / API tuning
PRICE_FETCH_MAX_ATTEMPTS = int(os.getenv("PRICE_FETCH_MAX_ATTEMPTS", "6"))
PRICE_FETCH_INITIAL_DELAY_SEC = int(os.getenv("PRICE_FETCH_INITIAL_DELAY_SEC", "30"))
PRICE_FETCH_MAX_DELAY_SEC = int(os.getenv("PRICE_FETCH_MAX_DELAY_SEC", "900"))
FX_FALLBACK_RATE = float(os.getenv("FX_FALLBACK_RATE", "11.0"))
FX_REQUEST_TIMEOUT_SEC = int(os.getenv("FX_REQUEST_TIMEOUT_SEC", "10"))
