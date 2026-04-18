import time
import pychromecast
import logging

logging.basicConfig(level=logging.INFO)

def test_modern_discovery():
    chromecasts = []
    
    def callback(chromecast):
        chromecasts.append(chromecast)
        
    print("Testing modern CastBrowser...")
    browser = pychromecast.CastBrowser(pychromecast.SimpleCastListener(callback), None)
    browser.start_discovery()
    
    print("Waiting 5 seconds for devices...")
    time.sleep(5)
    
    print(f"Found: {[c.name for c in chromecasts]}")
    browser.stop_discovery()

test_modern_discovery()
