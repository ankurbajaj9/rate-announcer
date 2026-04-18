import pychromecast
import logging

logging.basicConfig(level=logging.DEBUG)

def test_discovery():
    print("Testing pychromecast discovery...")
    chromecasts, browser = pychromecast.get_listed_chromecasts(friendly_names=['Living Room speaker'])
    print(f"Found: {chromecasts}")
    if browser:
        browser.stop_discovery()

test_discovery()
