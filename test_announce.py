#!/usr/bin/env python3
import sys
import pandas as pd
from datetime import date
from src.monitor import (
    fetch_quarter_prices,
    get_eur_to_sek,
    eur_mwh_to_sek_kwh,
    notify_google_home
)

def announce_current_rate():
    print("Fetching current electricity rate...")
    try:
        today = date.today()
        # Fetch today's prices
        prices_eur = fetch_quarter_prices(today)
        if prices_eur.empty:
            print("No price data available for today.")
            return

        # Fetch exchange rate
        fx = get_eur_to_sek(today)
        
        # Get current time in Stockholm
        now = pd.Timestamp.now(tz="Europe/Stockholm")
        
        # Get the price for the current time quarter
        current_eur = prices_eur.asof(now)
        
        if pd.isna(current_eur):
            print("Could not find the current price in today's data.")
            return
            
        current_sek = eur_mwh_to_sek_kwh(float(current_eur), fx)
        
        # Construct the message
        # We add "This is a test" so you know it's triggered manually
        message = f"Test announcement. The current electricity price is {current_sek:.2f} SEK per kilowatt hour."
        print(f"Message: {message}")
        print("Sending to Google Home...")
        
        # Play it!
        success = notify_google_home(message)
        if success:
            print("✅ Announcement played successfully!")
        else:
            print("❌ Failed to play the announcement. Check your Google Home name and network connection.")
            sys.exit(1)
            
    except Exception as e:
        print(f"Error during test script: {e}")
        sys.exit(1)

if __name__ == "__main__":
    announce_current_rate()
