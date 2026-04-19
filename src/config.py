import os
from dotenv import load_dotenv

load_dotenv()

# ENTSO-E API Configuration
ENTSOE_API_TOKEN = os.getenv("ENTSOE_API_TOKEN", "YOUR_ENTSOE_TOKEN_HERE")
PRICE_AREA = os.getenv("PRICE_AREA", "SE_3")

# Google Home Configuration
GOOGLE_HOME_NAME = os.getenv("GOOGLE_HOME_NAME", "Your Google Home Name")
TTS_LANGUAGE = os.getenv("TTS_LANGUAGE", "en")

# Threshold and Alert Configuration
THRESHOLD_PERCENT = float(os.getenv("THRESHOLD_PERCENT", "0.80"))
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

# Scheduling
SUMMARY_ANNOUNCE_DELAY_SEC = int(os.getenv("SUMMARY_ANNOUNCE_DELAY_SEC", "2"))
