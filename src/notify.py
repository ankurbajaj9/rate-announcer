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
import wave
import math
import struct

from src.config import (
    GOOGLE_HOME_HOST,
    GOOGLE_HOME_NAME,
    GOOGLE_HOME_PORT,
    SERVE_PORT,
    TTS_LANGUAGE,
    ENABLE_NOTIFICATIONS,
    EVENTS_DB_FILE,
)
from src.events import record_event

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


def notify_google_home(message: str, drop_time_iso: str | None = None) -> bool:
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
    # Global toggle: skip all notifications when disabled
    if not ENABLE_NOTIFICATIONS:
        log.info("Notifications disabled via ENABLE_NOTIFICATIONS; skipping TTS.")
        return True

    audio_path = None
    audio_dir = None
    server = None
    browser = None
    zconf = None
    cast = None
    success = False
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

        found_host = None
        found_port = None
        found_uuid = None
        found_model_name = None

        if GOOGLE_HOME_HOST:
            # Static IP configured — skip mDNS entirely to avoid discovery
            # timeouts and Zeroconf reconnect errors.
            log.info(
                "Connecting to Google Home '%s' at %s:%d (direct) ...",
                GOOGLE_HOME_NAME,
                GOOGLE_HOME_HOST,
                GOOGLE_HOME_PORT,
            )
            found_host = GOOGLE_HOME_HOST
            found_port = GOOGLE_HOME_PORT
        else:
            log.info("Discovering Google Home '%s' via mDNS ...", GOOGLE_HOME_NAME)

            discover_complete = threading.Event()

            # Using a single-element list as a mutable cell so add_callback can
            # safely access the devices dict even after `browser` is set to None.
            _devices_cell = [None]

            def add_callback(uuid, service):
                nonlocal found_host, found_port, found_uuid, found_model_name
                devices = _devices_cell[0]
                if devices is None:
                    return
                cast_info = devices.get(uuid)
                if cast_info is None:
                    return
                if cast_info.friendly_name == GOOGLE_HOME_NAME:
                    found_host = cast_info.host
                    found_port = cast_info.port
                    found_uuid = cast_info.uuid
                    found_model_name = cast_info.model_name
                    discover_complete.set()

            zconf = zeroconf.Zeroconf()
            browser = pychromecast.discovery.CastBrowser(
                pychromecast.discovery.SimpleCastListener(add_callback=add_callback),
                zconf,
            )
            # Populate the cell with the devices dict reference before starting
            # discovery. This ensures any in-flight callback fired after
            # `browser = None` below can still safely look up device info
            # without raising AttributeError.
            _devices_cell[0] = browser.devices
            browser.start_discovery()

            discover_complete.wait(timeout=10.0)

            # Tear down mDNS discovery immediately after the device is found.
            # Closing Zeroconf here ensures the cast object (created below via a
            # direct host connection) never holds a reference to a stopped Zeroconf
            # instance, which would otherwise trigger
            # "AssertionError: Zeroconf instance loop must be running" whenever
            # PyChromecast attempts a reconnect inside its socket-client thread.
            browser.stop_discovery()
            browser = None
            zconf.close()
            zconf = None

            if not found_host or not found_port:
                log.error(
                    "Google Home '%s' not found (host=%r, port=%r).",
                    GOOGLE_HOME_NAME,
                    found_host,
                    found_port,
                )
                return False

        # Connect directly via IP so reconnections bypass mDNS entirely.
        # Pass the full 5-tuple so pychromecast creates a HostServiceInfo
        # (not an MDNSServiceInfo) — this is what prevents the Zeroconf
        # reconnect assertion error.
        cast = pychromecast.get_chromecast_from_host(
            (found_host, found_port, found_uuid, found_model_name, GOOGLE_HOME_NAME)
        )

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
        success = True
        return True

    except Exception as e:
        log.exception("Notification failed: %s", e)
        return False
    finally:
        if server:
            server.shutdown()
            server.server_close()
        if cast:
            try:
                cast.disconnect(timeout=5)
            except Exception as exc:
                log.warning("Failed to disconnect Chromecast cleanly: %s", exc)
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
        # Record event to SQLite events DB
        try:
            record_event("notify_google_home", bool(success), message=message, drop_time_iso=drop_time_iso)
        except Exception as exc:
            log.warning("Failed to record event to DB %s: %s", EVENTS_DB_FILE, exc)


def notify_play_sound(duration_sec: float = 0.6, frequency_hz: int = 880) -> bool:
    """
    Generate short sine-wave WAV and play on configured Google Home.
    Returns True on success, False on failure.
    """
    # Global toggle: skip all notifications when disabled
    if not ENABLE_NOTIFICATIONS:
        log.info("Notifications disabled via ENABLE_NOTIFICATIONS; skipping sound.")
        return True

    audio_path = None
    audio_dir = None
    server = None
    browser = None
    zconf = None
    cast = None
    try:
        # generate temporary wav file
        audio_dir = tempfile.mkdtemp()
        tmp_fd, audio_path = tempfile.mkstemp(suffix=".wav", dir=audio_dir)
        os.close(tmp_fd)

        sample_rate = 44100
        amplitude = 16000
        n_samples = int(sample_rate * duration_sec)

        with wave.open(audio_path, "w") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            for i in range(n_samples):
                t = float(i) / sample_rate
                sample = amplitude * math.sin(2 * math.pi * frequency_hz * t)
                wf.writeframes(struct.pack('<h', int(sample)))

        server, audio_url = _serve_file(audio_path, SERVE_PORT)
        log.info("Serving sound: %s", audio_url)

        found_host = None
        found_port = None
        found_uuid = None
        found_model_name = None

        if GOOGLE_HOME_HOST:
            found_host = GOOGLE_HOME_HOST
            found_port = GOOGLE_HOME_PORT
        else:
            discover_complete = threading.Event()
            _devices_cell = [None]

            def add_callback(uuid, service):
                nonlocal found_host, found_port, found_uuid, found_model_name
                devices = _devices_cell[0]
                if devices is None:
                    return
                cast_info = devices.get(uuid)
                if cast_info is None:
                    return
                if cast_info.friendly_name == GOOGLE_HOME_NAME:
                    found_host = cast_info.host
                    found_port = cast_info.port
                    found_uuid = cast_info.uuid
                    found_model_name = cast_info.model_name
                    discover_complete.set()

            zconf = zeroconf.Zeroconf()
            browser = pychromecast.discovery.CastBrowser(
                pychromecast.discovery.SimpleCastListener(add_callback=add_callback),
                zconf,
            )
            _devices_cell[0] = browser.devices
            browser.start_discovery()
            discover_complete.wait(timeout=10.0)
            browser.stop_discovery()
            browser = None
            zconf.close()
            zconf = None

            if not found_host or not found_port:
                log.error("Google Home '%s' not found (host=%r, port=%r).", GOOGLE_HOME_NAME, found_host, found_port)
                return False

        cast = pychromecast.get_chromecast_from_host((found_host, found_port, found_uuid, found_model_name, GOOGLE_HOME_NAME))
        cast.wait()
        mc = cast.media_controller
        mc.play_media(audio_url, "audio/wav", stream_type="BUFFERED")
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
                log.error("Chromecast playback ended with idle_reason='%s' for '%s'.", idle_reason, GOOGLE_HOME_NAME)
                break
            time.sleep(PLAYBACK_CHECK_INTERVAL_SEC)

        if not playback_ready:
            log.error("Chromecast did not start playback for '%s'.", GOOGLE_HOME_NAME)
            return False

        # wait duration plus small buffer
        time.sleep(max(0.5, duration_sec + 0.2))
        return True

    except Exception as e:
        log.exception("Sound notification failed: %s", e)
        return False
    finally:
        if server:
            server.shutdown()
            server.server_close()
        if cast:
            try:
                cast.disconnect(timeout=5)
            except Exception as exc:
                log.warning("Failed to disconnect Chromecast cleanly: %s", exc)
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
