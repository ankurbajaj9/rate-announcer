# Todo List

## Done
- [x] Create project directory structure ([src/](src/))
- [x] Create configuration management system ([src/config.py](src/config.py), [.env.example](.env.example))
- [x] Move core logic from root to [src/monitor.py](src/monitor.py)
- [x] Create [main.py](main.py) as entry point
- [x] Update [README.md](README.md) with new project structure
- [x] Migrate PyChromecast discovery to modern `CastBrowser` architecture
- [x] Announce daily summary with max, min, and average rates
- [x] Add comprehensive unit tests with mocked Google Home discovery ([test_monitor.py](test_monitor.py))
- [x] Implement CLI script for manually testing announcements ([test_announce.py](test_announce.py))
- [x] Refactor `src/monitor.py` into focused modules: [src/prices.py](src/prices.py) (ENTSO-E + FX), [src/notify.py](src/notify.py) (TTS + Chromecast), [src/monitor.py](src/monitor.py) (scheduling)
- [x] Move hardcoded cache paths and scheduling delay into [src/config.py](src/config.py)
- [x] Finalize project cleanup — removed legacy discovery scripts (`test_discovery*.py`)
- [x] Refactor `_build_summary_message` to accept `high: tuple[float, str]` and `low: tuple[float, str]` instead of four separate parameters

## To-do
- [ ] Add more comprehensive logging options
- [ ] Containerize the application (Dockerfile)
- [ ] Implement multi-speaker support
- [ ] Add support for different notification languages (currently supports 'sv' via config)
- [ ] Refactor scheduling: Create a daily planner that fetches tomorrow's prices once a day (e.g., at 13:00), pre-calculates the exact timestamps when boundaries are crossed, and schedules exact one-off runs (e.g., using `at` or an async timer) instead of a constant 15-minute polling loop.
