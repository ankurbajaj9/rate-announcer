import time
from src.monitor import start_scheduler

if __name__ == "__main__":
    print("Starting rate-announcer scheduler module...")
    try:
        start_scheduler()
        # Keep the main thread alive while the BackgroundScheduler runs
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        print("Shutting down scheduler...")
