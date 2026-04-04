# Stockholm Electricity Price Monitor

Fetches SE3 15-minute spot prices from ENTSO-E Transparency Platform and announces a Google Home alert when the current quarter price exceeds a defined threshold of today's maximum.

## Installation

1.  **Clone the repository**:
    ```bash
    git clone <repository-url>
    cd rate-announcer
    ```

2.  **Setup Virtual Environment**:
    ```bash
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
    ```

3.  **Configure Environment Variables**:
    Copy `.env.example` to `.env` and fill in your details:
    ```bash
    cp .env.example .env
    ```
    - `ENTSOE_API_TOKEN`: Get a free token from [ENTSO-E Transparency Platform](https://transparency.entsoe.eu) (My Account → Web API Security Token).
    - `GOOGLE_HOME_NAME`: Exact name of your Google Home device.
    - `PRICE_AREA`: Default is `SE_3` (Stockholm).

## Usage

Run the monitor manually:
```bash
python main.py
```

## Automation (Systemd)

Refer to [SETUP.md](SETUP.md) for detailed instructions on setting up a systemd timer to run the monitor every 15 minutes.

## Project Structure

- `main.py`: Entry point for the application.
- `src/monitor.py`: Core logic for fetching prices and notifying Google Home.
- `src/config.py`: Configuration management using environment variables.
- `.env`: (Not committed) Local environment secrets.
