# Todo List

## Done
- [x] Create project directory structure ([src/](src/))
- [x] Create configuration management system ([src/config.py](src/config.py), [.env.example](.env.example))
- [x] Move core logic from root to [src/monitor.py](src/monitor.py)
- [x] Create [main.py](main.py) as entry point
- [x] Update [README.md](README.md) with new project structure

## In Progress
- [ ] Finalize project cleanup (removing legacy files)

## To-do
- [ ] Add more comprehensive logging options
- [ ] Implement a command-line interface (CLI) for testing individual components
- [ ] Containerize the application (Dockerfile)
- [ ] Add unit tests for price calculation logic
- [ ] Implement multi-speaker support
- [ ] Add support for different notification languages (currently supports 'sv' via config)
- [ ] Refactor scheduling: Create a daily planner that fetches tomorrow's prices once a day (e.g., at 13:00), pre-calculates the exact timestamps when boundaries are crossed, and schedules exact one-off runs (e.g., using `at` or an async timer) instead of a constant 15-minute polling loop.
