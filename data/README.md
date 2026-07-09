# Data Directory

This directory holds both static seed dataset files and dynamic runtime-generated data files for the SurakshaAI Safety Dashboard application.

## Directory Structure

### 1. Static Seed Data (Tracked by Git)
- `plant_data.csv`: A static historical csv seed dataset holding simulated sensor logs, gas ppm levels, reactor temperature, pressure, and permit states used to mock/simulate the SCADA metrics panel.

### 2. Runtime Generated Files (Ignored by Git)
- `alerts.db`: Legacy safety alerts SQLite database.
- `alerts_v2.db` / `alerts_v2.db-shm` / `alerts_v2.db-wal`: Live Unified Alert Coordinator SQLite databases and write-ahead logs containing active and resolved safety incidents.
- `actions.json`: Auto-generated knowledge base configuration file detailing prescriptive safety guidelines and recommendations.
- `coordinator.lock`: A process locking file to prevent multiple instances from running concurrently.
- `suraksha.log`: Logging information from the live dashboard and background workers.
