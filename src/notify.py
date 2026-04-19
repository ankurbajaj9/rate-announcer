"""
TTS generation and Google Home / Chromecast playback.

Responsibilities:
- Generate MP3 audio from text via gTTS
- Serve the MP3 over a temporary local HTTP server
- Discover and connect to the target Google Home via PyChromecast
- Play the audio and verify that playback actually starts
"""

import http.server
import logging
import os
import socket
import tempfile
import threading
import time

import pychromecast
import zeroconf
from gtts import gTTS

from src.config import (
    GOOGLE_HOME_NAME,
    SERVE_PORT,
    TTS_LANGUAGE,
)

log = logging.getLogger(__name__)

# How long to wait between playback state polls (seconds)
PLAYBACK_CHECK_INTERVAL_SEC = 0.5
# Maximum number of state polls before declaring playback failed (total: 10 s)
MAX_PLAYBACK_CHECK_ATTEMPTS = 20


def get_local_ip() -> str:
    """Return the local IPv4 address used to reach the internet."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    """HTTP request handler that suppresses all access-log output."""

    def log_message(self, *_):
        pass


def _serve_file(filepath: str, port: int):
    """
    Spin up a temporary single-file HTTP server on *port*.
    Returns (server, public_url) where public_url is reachable by Chromecast.
    """
    directory = os.path.dirname(filepath)
    filename = os.path.basename(filepath)

    class _Handler(_QuietHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=directory, **kw)

    server = http.server.HTTPServer(("", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://{get_local_ip()}:{port}/{filename}"


def notify_google_home(message: str) -> bool:
    """
    Speak *message* via the configured Google Home device.

    Steps:
    1. Generate a TTS MP3 with gTTS.
    2. Serve the file over a temporary local HTTP server.
    3. Discover the Google Home via mDNS / CastBrowser.
    4. Play the audio and poll until playback is confirmed active.
    5. Wait for the estimated audio duration, then clean up.

    Returns True on success, False on any failure.
    """
    audio_path = None
    audio_dir = None
    server = None
    browser = None
    zconf = None
    try:
        log.info("Generating TTS audio ...")
        tts = gTTS(text=message, lang=TTS_LANGUAGE)

        # Create a dedicated temp directory so the HTTP server only exposes one file
        audio_dir = tempfile.mkdtemp()
        tmp_fd, audio_path = tempfile.mkstemp(suffix=".mp3", dir=audio_dir)
        os.close(tmp_fd)
        tts.save(audio_path)

        server, audio_url = _serve_file(audio_path, SERVE_PORT)
        log.info("Serving audio: %s", audio_url)

        log.info("Connecting to Google Home: '%s' ...", GOOGLE_HOME_NAME)

        cast = None
        discover_complete = threading.Event()

        def add_callback(uuid, service):
            nonlocal cast
            cast_info = browser.devices.get(uuid)
            if cast_info is None:
                return
            if cast_info.friendly_name == GOOGLE_HOME_NAME:
                cast = pychromecast.get_chromecast_from_cast_info(cast_info, zconf)
                discover_complete.set()

        zconf = zeroconf.Zeroconf()
        browser = pychromecast.discovery.CastBrowser(
            pychromecast.discovery.SimpleCastListener(add_callback=add_callback),
            zconf,
        )
        browser.start_discovery()

        discover_complete.wait(timeout=10.0)

        if not cast:
            log.error("Google Home '%s' not found.", GOOGLE_HOME_NAME)
            return False

        cast.wait()

        mc = cast.media_controller
        # TTS is a finite MP3 file; use Chromecast-compatible audio/mpeg as BUFFERED media.
        mc.play_media(audio_url, "audio/mpeg", stream_type="BUFFERED")
        mc.block_until_active(timeout=30)

        playback_ready = False
        for _ in range(MAX_PLAYBACK_CHECK_ATTEMPTS):
            mc.update_status()
            status = mc.status
            if status is None:
                time.sleep(PLAYBACK_CHECK_INTERVAL_SEC)
                continue

            state = status.player_state
            idle_reason = status.idle_reason

            if state in {"PLAYING", "BUFFERING"}:
                playback_ready = True
                break
            if state == "IDLE" and idle_reason in {"ERROR", "CANCELLED", "INTERRUPTED"}:
                log.error(
                    "Chromecast playback ended with idle_reason='%s' for '%s'.",
                    idle_reason,
                    GOOGLE_HOME_NAME,
                )
                break
            time.sleep(PLAYBACK_CHECK_INTERVAL_SEC)

        if not playback_ready:
            log.error("Chromecast did not start playback for '%s'.", GOOGLE_HOME_NAME)
            return False

        # Estimate message duration and wait for it to finish playing
        wait_time = max(10, len(message) // 8)
        time.sleep(wait_time)
        return True

    except Exception as e:
        log.exception("Notification failed: %s", e)
        return False
    finally:
        if server:
            server.shutdown()
            server.server_close()
        if browser:
            browser.stop_discovery()
        if zconf:
            zconf.close()
        if audio_path and os.path.exists(audio_path):
            os.unlink(audio_path)
        if audio_dir and os.path.exists(audio_dir):
            try:
                os.rmdir(audio_dir)
            except OSError as exc:
                log.warning("Failed to remove temp audio directory %s: %s", audio_dir, exc)
