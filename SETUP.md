# Stockholm Electricity Price Monitor — Setup Guide

## How it works

Unlike some other tools that rely on a specific electricity provider's API (like Tibber's API), this project is completely **provider-agnostic**. It uses the raw, upstream market data from the **ENTSO-E Transparency Platform**.

This means it works perfectly whether your contract is with Telinet, Vattenfall, E.ON, Greenely, or anyone else — you do not need to be a Tibber customer to get electricity price alerts.

```
ENTSO-E (Day-ahead prices)
        │
        ▼
  Raspberry Pi / Server (runs every 15 min or 1 hour)
  ├── Fetches today's prices via ENTSO-E API
  ├── Converts EUR/MWh to SEK/kWh via Frankfurter API
  ├── Compares current price window to threshold (e.g., 80% of daily max)
  └── If exceeded → gTTS MP3 → local HTTP → Chromecast → Google Home speaks
```

---

## 1. Install dependencies

It is recommended to use a virtual environment or Conda.

### Using venv
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Using Conda
```bash
conda create --name rate-announcer python=3.12
conda activate rate-announcer
pip install -r requirements.txt
```

---

## 2. Configuration

1.  **Environment Variables**: Copy `.env.example` to `.env` and fill in your details.
    ```bash
    cp .env.example .env
    ```
2.  **ENTSO-E API Token**: Since this project doesn't use the Tibber API or any provider-specific system, you need a token from the central European platform (ENTSO-E):
    - Register for free at [ENTSO-E Transparency Platform](https://transparency.entsoe.eu/)
    - **Note:** ENTSO-E requires you to request API access before the token option appears. Send an email to `transparency@entsoe.eu` with the subject "Restful API access" using your registered email address.
    - Once access is granted by their team, go to **My Account** → **Web API Security Token** to generate your key.
3.  **Google Home Name**: Find the exact name in the Google Home app (e.g., "Kitchen speaker").

---

## 3. Test manually

Ensure your environment is active (or use `conda run`):

```bash
python main.py
```

To run unit tests:
```bash
python test_monitor.py
```

---

## 4. Schedule with systemd (For Linux/Raspberry Pi)

```bash
# Create service file
sudo tee /etc/systemd/system/price-monitor.service <<EOF
[Unit]
Description=Stockholm Electricity Price Monitor
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$(whoami)
WorkingDirectory=$PWD
ExecStart=$HOME/miniforge3/envs/rate-announcer/bin/python $PWD/main.py
StandardOutput=journal
StandardError=journal
EOF

# Create timer file
sudo tee /etc/systemd/system/price-monitor.timer <<'EOF'
[Unit]
Description=Run electricity price monitor
Requires=price-monitor.service

[Timer]
OnBootSec=2min
# Use 15min for kvartspris (e.g. Telinet), or 1h for hourly spot prices (e.g. Tibber, Greenely)
OnUnitActiveSec=15min
AccuracySec=30s

[Install]
WantedBy=timers.target
EOF

# Enable and start the timer
sudo systemctl enable --now price-monitor.timer
```

EOF

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable --now price-monitor.timer

# Check status
sudo systemctl list-timers price-monitor.timer
journalctl -u price-monitor.service -f   # live logs
```

---

## Alternative: cron (simpler)

```bash
crontab -e
# Add this line:
*/15 * * * *  /home/pi/venv/bin/python /home/pi/price_monitor.py >> /tmp/price_monitor.log 2>&1
```

---

## Optional: Swedish voice

In `price_monitor.py` change:
```python
TTS_LANGUAGE = "sv"
```

---

## Optional: Provider-Specific APIs (e.g., Tibber)

While this project is configured to use **ENTSO-E** so it works for *any* electricity provider, some providers like **Tibber** or **Greenely** offer their own developer APIs. If you prefer to use your provider's specific data, you could technically replace the `fetch_quarter_prices_today()` function in `src/monitor.py` with an API call to your provider. 

However, using the default ENTSO-E setup ensures your monitor will continue working flawlessly even if you switch electricity providers in the future.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Google Home not found" | Confirm Pi and speaker are on same subnet; try `python -c "import pychromecast; cs,_ = pychromecast.get_chromecasts(); print([c.name for c in cs])"` |
| Audio plays but silent | Check speaker volume in Google Home app |
| Prices not fetched | API updates ~13:00 CET; run after that time or check URL manually |
| Cooldown too long | Delete `/tmp/price_monitor_state` to reset |
