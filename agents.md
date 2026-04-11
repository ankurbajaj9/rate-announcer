# Copilot Agents

This repository uses specialized agents to help with development.

## Project Summary

The **Rate Announcer** project is a Python tool designed to monitor electricity spot prices (SE3 area) from ENTSO-E and announce high-price alerts via Google Home. 

## Agent Context

- **Tech Stack**: Python, Pandas, Entsoe-py, gTTS, PyChromecast.
- **Entry Point**: [main.py](main.py)
- **Core Logic**: [src/monitor.py](src/monitor.py)
- **Configuration**: [src/config.py](src/config.py) and [.env](.env)

## Key Responsibilities

- **Developer Agent**: Handles adding new features, like support for additional price areas or different notification systems. check if the dependencies are latest.
- **Maintenance Agent**: Updates dependencies in [requirements.txt](requirements.txt) and ensures the systemd service (see [SETUP.md](SETUP.md)) is configured correctly.
- **Security Agent**: Monitors the use of API tokens and ensures `.env` is properly ignored in `.gitignore`.
