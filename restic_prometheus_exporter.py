import os
import subprocess
import json
import sys
import configparser  # For reading configuration files
from prometheus_client import start_http_server, Gauge
import time
import datetime  # Import datetime for timestamp conversion

# Define Prometheus metrics
SNAPSHOT_COUNT = Gauge('restic_snapshot_count', 'Number of restic snapshots')
SNAPSHOT_DETAILS = Gauge('restic_snapshot_details', 'Details of each restic snapshot',
                         ['host', 'id', 'date', 'tags', 'directory'])
SNAPSHOT_TIMESTAMP = Gauge('restic_snapshot_timestamp', 'Timestamp of each restic snapshot',
                           ['host', 'id', 'date'])

def load_config(config_file=None):
    """Loads configuration from a file or environment variables."""
    config = {}
    if config_file:
        parser = configparser.ConfigParser()
        parser.read(config_file)
        config['RESTIC_REPOSITORY'] = parser.get('restic', 'repository', fallback=None)
        config['AWS_ACCESS_KEY_ID'] = parser.get('aws', 'access_key_id', fallback=None)
        config['AWS_SECRET_ACCESS_KEY'] = parser.get('aws', 'secret_access_key', fallback=None)
        config['RESTIC_PASSWORD'] = parser.get('restic', 'password', fallback=None)
        config['EXPORTER_PORT'] = parser.getint('exporter', 'port', fallback=9150)
        config['UPDATE_INTERVAL'] = parser.getint('exporter', 'update_interval', fallback=30)
    else:
        config['RESTIC_REPOSITORY'] = os.getenv('RESTIC_REPOSITORY')
        config['AWS_ACCESS_KEY_ID'] = os.getenv('AWS_ACCESS_KEY_ID')
        config['AWS_SECRET_ACCESS_KEY'] = os.getenv('AWS_SECRET_ACCESS_KEY')
        config['RESTIC_PASSWORD'] = os.getenv('RESTIC_PASSWORD')
        config['EXPORTER_PORT'] = int(os.getenv('EXPORTER_PORT', 9150))
        config['UPDATE_INTERVAL'] = int(os.getenv('UPDATE_INTERVAL', 30))

    # Validate required fields
    if not all([config['RESTIC_REPOSITORY'], config['RESTIC_PASSWORD']]):
        print("Error: Missing required configuration for RESTIC_REPOSITORY or RESTIC_PASSWORD.", file=sys.stderr)
        sys.exit(1)

    return config

def run_restic_command(command, env):
    """Runs a restic command with the provided environment variables."""
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, text=True, env=env)
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {e.stderr}", file=sys.stderr)
        sys.exit(1)

def parse_size(size_str):
    """Parses a size string (e.g., '3.419 GiB') and converts it to bytes(IEC)."""
    size_units = {"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3, "TiB": 1024**4}
    parts = size_str.split()
    if len(parts) != 2:
        return 0  # Default to 0 if the size format is unexpected
    size_value, size_unit = parts
    try:
        size_value = float(size_value)
        return size_value * size_units.get(size_unit, 1)  # Convert to bytes
    except (ValueError, KeyError):
        return 0  # Default to 0 if parsing fails

def export_snapshots(config):
    """Exports snapshots information from restic."""
    command = ["restic", "-r", config['RESTIC_REPOSITORY'], "snapshots"]
    env = os.environ.copy()
    env.update({
        'AWS_ACCESS_KEY_ID': config['AWS_ACCESS_KEY_ID'],
        'AWS_SECRET_ACCESS_KEY': config['AWS_SECRET_ACCESS_KEY'],
        'RESTIC_PASSWORD': config['RESTIC_PASSWORD']
    })
    output = run_restic_command(command, env)

    # Parse human-readable output to extract fields
    snapshots = []
    lines = output.splitlines()
    for line in lines:
        # Skip header lines and empty lines
        if line.startswith("ID") or line.startswith("---") or line.strip() == "":
            continue

        # Split the line into fields
        fields = line.split()
        if len(fields) < 6:
            continue  # Skip malformed lines

        # Extract fields
        snapshot_id = fields[0]
        date = fields[1] + " " + fields[2]
        host = fields[3]
        tags = fields[4]
        directory = fields[5]
        size_str = " ".join(fields[6:])  # Combine remaining fields for size
        size = parse_size(size_str)  # Parse size from the combined string

        # Append snapshot details
        snapshots.append({
            "id": snapshot_id,
            "time": date,
            "hostname": host,
            "tags": tags,
            "directory": directory,
            "size": size
        })

    return snapshots

def convert_to_timestamp(date_str):
    """Converts a date string (e.g., '2024-11-07 16:26:17') to a Unix timestamp."""
    try:
        dt = datetime.datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
        return int(dt.timestamp())
    except ValueError:
        return 0  # Default to 0 if parsing fails

def update_prometheus_metrics(config):
    """Fetches the restic snapshots and updates Prometheus metrics."""
    snapshots = export_snapshots(config)

    # Update snapshot count metric
    SNAPSHOT_COUNT.set(len(snapshots))

    # Update snapshot details metrics
    for snapshot in snapshots:
        # Ensure the size is a numeric value
        numeric_size = float(snapshot["size"]) if isinstance(snapshot["size"], (int, float)) else 0

        # Ensure other parameters are properly formatted
        snapshot_id = str(snapshot["id"]).strip() if snapshot["id"] else "unknown"
        snapshot_date = str(snapshot["time"]).strip() if snapshot["time"] else "unknown"
        snapshot_host = str(snapshot["hostname"]).strip() if snapshot["hostname"] else "unknown"
        snapshot_tags = str(snapshot["tags"]).strip() if snapshot["tags"] else "none"
        snapshot_directory = str(snapshot["directory"]).strip() if snapshot["directory"] else "unknown"

        # Convert the date to a Unix timestamp
        timestamp = convert_to_timestamp(snapshot_date)

        # Set the metric with labels and use the size as the value
        SNAPSHOT_DETAILS.labels(
            host=snapshot_host,
            id=snapshot_id,
            date=str(timestamp),  # Use the Unix timestamp as the date label
            tags=snapshot_tags,
            directory=snapshot_directory  # Group by directory
        ).set(numeric_size)

        # Set the timestamp metric
        SNAPSHOT_TIMESTAMP.labels(
            host=snapshot_host,
            id=snapshot_id,
            date=str(timestamp)  # Use the Unix timestamp as the date label
        ).set(timestamp)

def main():
    # Load configuration
    config_file = sys.argv[1] if len(sys.argv) > 1 else None
    config = load_config(config_file)

    # Start the Prometheus server on the configured port
    start_http_server(config['EXPORTER_PORT'])
    print(f"Prometheus metrics server is running on :{config['EXPORTER_PORT']}/metrics")

    # Collect data at the configured interval
    while True:
        update_prometheus_metrics(config)
        time.sleep(config['UPDATE_INTERVAL'])  # Adjust based on the configured interval

if __name__ == "__main__":
    main()

