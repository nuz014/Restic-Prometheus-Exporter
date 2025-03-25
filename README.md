# Restic Prometheus Exporter

This project provides a Prometheus exporter for monitoring Restic snapshots. It collects details about Restic snapshots, such as ID, date, host, tags, directory, and size, and exposes them as Prometheus metrics.

## Features

- Exports the number of Restic snapshots.
- Exports detailed information about each snapshot, including:
  - Snapshot ID
  - Date
  - Host
  - Tags
  - Directory
  - Size (in bytes)

## Prerequisites

- Python 3.6 or higher
- Restic installed and accessible in your `PATH`
- Prometheus installed and configured to scrape metrics

## Installation

1. Clone this repository:
   ```bash
   git clone https://github.com/your-repo/restic-exporter.git
   cd restic-exporter
   ```

2. Install required Python dependencies:
   ```bash
   pip install prometheus_client
   ```

3. Configure your Restic repository and credentials in the `config.ini` file:
   ```ini
   [restic]
   repository =
   password =

   [aws]
   access_key_id =
   secret_access_key =
   ```

## Usage

1. Run the exporter:
   ```bash
   python restic_prometheus_exporter.py config.ini
   ```

2. The exporter will start a Prometheus metrics server on port `9150` and expose metrics at:
   ```
   http://localhost:9150/metrics
   ```

3. Add the following scrape configuration to your Prometheus configuration file (`prometheus.yml`):
   ```yaml
   scrape_configs:
     - job_name: "restic_exporter"
       static_configs:
         - targets: ["localhost:9150"]
   ```

4. Restart Prometheus to apply the changes.

## Metrics

The following metrics are exposed:

- `restic_snapshot_count`: The total number of Restic snapshots.
- `restic_snapshot_details`: Details of each Restic snapshot, with the following labels:
  - `id`: Snapshot ID
  - `date`: Snapshot date and time
  - `host`: Hostname of the snapshot
  - `tags`: Tags associated with the snapshot
  - `directory`: Directory included in the snapshot
  - `size`: Size of the snapshot in bytes

## Example Output

Example Prometheus metrics:
```
# HELP restic_snapshot_count Number of restic snapshots
# TYPE restic_snapshot_count gauge
restic_snapshot_count 2

# HELP restic_snapshot_details Details of each restic snapshot
# TYPE restic_snapshot_details gauge
restic_snapshot_details{id="6c69486e",date="2024-11-07 16:26:17",host="metrics",tags="manual,prometheus",directory="/var/lib/prometheus",size="3670511616"} 1
restic_snapshot_details{id="bbfc4e6d",date="2024-11-07 16:26:17",host="logs",tags="manual,graylog-server",directory="/usr/share/graylog-server/plugin",size="66074316"} 1
```

## Troubleshooting

- If you encounter errors, ensure that:
  - Restic is installed and accessible in your `PATH`.
  - The `config.ini` file is correctly configured with your repository and credentials.
  - The Prometheus server is running and configured to scrape the exporter.

## License

This project is licensed under the MIT License. See the `LICENSE` file for details.
