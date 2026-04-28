import time
from src.monitor import start_scheduler
from src.web import set_scheduler, start_web_server

if __name__ == "__main__":
    print("Starting rate-announcer scheduler module...")
    try:
        scheduler = start_scheduler()
        set_scheduler(scheduler)
        start_web_server()
        # Keep the main thread alive while the BackgroundScheduler runs
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        print("Shutting down scheduler...")
