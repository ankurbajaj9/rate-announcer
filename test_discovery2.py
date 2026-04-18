import pychromecast
import logging

logging.basicConfig(level=logging.DEBUG)

def test():
    print("Testing pychromecast get_chromecasts()...")
    chromecasts, browser = pychromecast.get_chromecasts(tries=3, retry_wait=2.0, timeout=10.0)
    print(f"All found: {[c.name for c in chromecasts]}")
    target = next((c for c in chromecasts if c.name == 'Living Room speaker'), None)
    print(f"Target found: {target.name if target else None}")
    if browser:
        browser.stop_discovery()

test()
