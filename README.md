# Stockholm Electricity Price Monitor

Fetches SE3 15-minute spot prices from ENTSO-E Transparency Platform and announces a Google Home alert when the current quarter price exceeds a defined threshold of today's maximum.

## Installation

1.  **Clone the repository**:
    ```bash
    git clone <repository-url>
    cd rate-announcer
    ```

2.  **Setup Conda Environment**:
    ```bash
    conda create --name rate-announcer python=3.12
    conda activate rate-announcer
    pip install -r requirements.txt
    ```

    To run tests:
    ```bash
    pip install -r requirements-test.txt
    ```

3.  **Configure Environment Variables**:
    Copy `.env.example` to `.env` and fill in your details:
    ```bash
    cp .env.example .env
    ```
    - `ENTSOE_API_TOKEN`: Get a free token from [ENTSO-E Transparency Platform](https://transparency.entsoe.eu). You must register an account and then send an email to `transparency@entsoe.eu` with the subject "Restful API access" to request access. Once approved, generate the token under (My Account → Web API Security Token).
    - `GOOGLE_HOME_NAME`: Exact name of your Google Home device.
    - `PRICE_AREA`: Default is `SE_3` (Stockholm).

## Usage

Run the monitor manually:
```bash
python main.py
```

## Docker on Raspberry Pi

The app can run as a container on Raspberry Pi with one image for both the scheduler and the web UI.

1.  **Build the image**:
    ```bash
    docker build -t rate-announcer .
    ```

2.  **Run it with host networking** so Chromecast discovery and the local TTS HTTP server stay reachable on your LAN:
    ```bash
    docker run -d \
      --name rate-announcer \
      --network host \
      --restart unless-stopped \
      --env-file .env \
      rate-announcer
    ```

3.  **Or use Docker Compose**:
    ```bash
    docker compose up -d --build
    ```

The dashboard will be available on the configured `WEB_PORT`, and the audio server uses `SERVE_PORT` from `src/config.py`.

## Automation (Systemd)

Refer to [SETUP.md](SETUP.md) for detailed instructions on setting up a systemd service to run the monitor as a background daemon.

## Automation (GitHub Actions)

This repository includes a workflow at `/home/runner/work/rate-announcer/rate-announcer/.github/workflows/publish-image.yml` that builds and pushes `ankurbajaj9/home:rate-announcer` on every successful push to `main`.

Configure these repository secrets before using it:
- `DOCKERHUB_USERNAME`
- `DOCKERHUB_TOKEN`

## Project Structure

- `main.py`: Entry point for the application.
- `src/monitor.py`: Core logic for fetching prices and notifying Google Home.
- `src/config.py`: Configuration management using environment variables.
- `.env`: (Not committed) Local environment secrets.
