# Restic Prometheus Exporter

A Prometheus exporter for monitoring Restic backup repositories. Exposes snapshot details, repository health, storage usage, and backup freshness as Prometheus metrics. Includes a Grafana dashboard for visualization.

## Features

- Snapshot count and per-snapshot details (host, tags, directory, timestamp)
- Backup freshness tracking (latest snapshot age per host/directory)
- Per-directory snapshot size tracking (from snapshot summary data)
- Lock detection
- Repository size metrics (raw disk usage, restore size, deduplication ratio)
- All commands run with `--no-lock` so the exporter works while backups are running.

## Metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `restic_snapshot_count` | Gauge | — | Total number of snapshots |
| `restic_snapshot_timestamp` | Gauge | host, id, date, tags, directory | Unix timestamp of each snapshot |
| `restic_snapshot_latest_timestamp` | Gauge | host, directory | Timestamp of the newest snapshot per host/directory |
| `restic_snapshot_latest_size_bytes` | Gauge | host, directory | Size in bytes of the latest snapshot per host/directory |
| `restic_locks_total` | Gauge | — | Number of active repository locks |
| `restic_repo_raw_size_bytes` | Gauge | — | Repository size on disk |
| `restic_repo_restore_size_bytes` | Gauge | — | Total restore size of all snapshots |
| `restic_repo_file_count` | Gauge | — | Total number of files across all snapshots |

## Prerequisites

- Python 3.6 or higher
- Restic installed and accessible in your `PATH`
- Prometheus installed and configured to scrape metrics

## Installation

1. Clone this repository:
   ```bash
   git clone https://github.com/<owner>/restic-exporter.git
   cd restic-exporter
   ```

2. Install required Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Copy and edit the configuration file:
   ```bash
   cp "config example.ini" config.ini
   ```

4. Run the exporter:
   ```bash
   python restic_prometheus_exporter.py config.ini
   ```

## Configuration

Edit the configuration file with your Restic repository details. Use `config.ini` in the project directory.

```ini
[restic]
repository = s3:https://your-s3-endpoint/bucket-name
password = your-restic-password

[aws]
access_key_id = your-access-key
secret_access_key = your-secret-key

[exporter]
port = 9150
# update_interval = 60
schedule_time = 14:00
timezone = Europe/Oslo
```

| Option | Default | Description |
|--------|---------|-------------|
| `port` | `9150` | HTTP port for the metrics endpoint |
| `update_interval` | `60` | How often to refresh metrics (minutes). Ignored if `schedule_time` is set |
| `schedule_time` | — | Run once daily at this time (HH:MM). Overrides `update_interval` |
| `timezone` | `UTC` | Timezone for `schedule_time` (e.g. `Europe/Oslo`) |

All options can also be set via environment variables: `RESTIC_REPOSITORY`, `RESTIC_PASSWORD`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `EXPORTER_PORT`, `UPDATE_INTERVAL`, `SCHEDULE_TIME`, `TIMEZONE`.

## Usage

1. Metrics are available at:
   ```
   http://localhost:9150/metrics
   ```

2. Add to your Prometheus configuration (`prometheus.yml`):
   ```yaml
   scrape_configs:
     - job_name: "restic_exporter"
       static_configs:
         - targets: ["localhost:9150"]
   ```

## Grafana Dashboard

Import `restic_grafana_dashboard.json` into Grafana. The dashboard includes:

- **Health Overview** — Total snapshots, active locks, time since last backup
- **Storage** — Repository disk usage, total backup data size, deduplication ratio
- **Backup Freshness** — Time since last backup per host/directory with a 24-hour threshold line
- **Snapshots** — Latest snapshot per directory with timestamp and size
- **Repository Size Over Time** — Disk usage and restore size trends
- **Snapshot Size per Directory** — How each backup directory is growing over time

The dashboard uses a templated Prometheus datasource so you can select your own when importing.

## Troubleshooting

- Ensure Restic is installed and accessible in your `PATH`
- Ensure `config.ini` is correctly configured with your repository and credentials
- If the repository is locked by a running backup, the exporter will still work (all commands use `--no-lock`)
- Check the exporter console output for error messages
