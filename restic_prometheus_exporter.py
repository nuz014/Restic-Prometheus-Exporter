import os
import re
import subprocess
import json
import sys
import configparser
from zoneinfo import ZoneInfo
from prometheus_client import start_http_server, Gauge
import time
import datetime

# --- Prometheus Metrics ---

# Snapshot metrics
SNAPSHOT_COUNT = Gauge('restic_snapshot_count', 'Number of restic snapshots')
SNAPSHOT_TIMESTAMP = Gauge('restic_snapshot_timestamp', 'Timestamp of each restic snapshot',
                           ['host', 'id', 'date', 'tags', 'directory'])
SNAPSHOT_LATEST_TIMESTAMP = Gauge('restic_snapshot_latest_timestamp',
                                  'Timestamp of the latest snapshot per host and directory',
                                  ['host', 'directory'])
SNAPSHOT_LATEST_SIZE = Gauge('restic_snapshot_latest_size_bytes',
                             'Size in bytes of the latest snapshot per host and directory',
                             ['host', 'directory'])

# Repository health metrics
LOCKS_TOTAL = Gauge('restic_locks_total', 'Number of active locks in the restic repository')

# Repository size metrics
REPO_RAW_SIZE = Gauge('restic_repo_raw_size_bytes', 'Raw size of the restic repository on disk')
REPO_RESTORE_SIZE = Gauge('restic_repo_restore_size_bytes', 'Total restore size of all snapshots')
REPO_FILE_COUNT = Gauge('restic_repo_file_count', 'Total number of files across all snapshots')

def log(msg):
    """Prints a timestamped log message."""
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")


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
        config['UPDATE_INTERVAL'] = parser.getint('exporter', 'update_interval', fallback=60) * 60
        config['SCHEDULE_TIME'] = parser.get('exporter', 'schedule_time', fallback=None)
        config['TIMEZONE'] = parser.get('exporter', 'timezone', fallback='UTC')
    else:
        config['RESTIC_REPOSITORY'] = os.getenv('RESTIC_REPOSITORY')
        config['AWS_ACCESS_KEY_ID'] = os.getenv('AWS_ACCESS_KEY_ID')
        config['AWS_SECRET_ACCESS_KEY'] = os.getenv('AWS_SECRET_ACCESS_KEY')
        config['RESTIC_PASSWORD'] = os.getenv('RESTIC_PASSWORD')
        config['EXPORTER_PORT'] = int(os.getenv('EXPORTER_PORT', 9150))
        config['UPDATE_INTERVAL'] = int(os.getenv('UPDATE_INTERVAL', 60)) * 60
        config['SCHEDULE_TIME'] = os.getenv('SCHEDULE_TIME')
        config['TIMEZONE'] = os.getenv('TIMEZONE', 'UTC')

    if not all([config['RESTIC_REPOSITORY'], config['RESTIC_PASSWORD']]):
        print("Error: Missing required configuration for RESTIC_REPOSITORY or RESTIC_PASSWORD.", file=sys.stderr)
        sys.exit(1)

    return config


def get_restic_env(config):
    """Returns environment variables for restic commands."""
    env = os.environ.copy()
    env['RESTIC_PASSWORD'] = config['RESTIC_PASSWORD']
    if config.get('AWS_ACCESS_KEY_ID'):
        env['AWS_ACCESS_KEY_ID'] = config['AWS_ACCESS_KEY_ID']
    if config.get('AWS_SECRET_ACCESS_KEY'):
        env['AWS_SECRET_ACCESS_KEY'] = config['AWS_SECRET_ACCESS_KEY']
    return env


def run_restic_command(command, env):
    """Runs a restic command. Returns stdout on success, None on failure."""
    cmd_str = ' '.join(command[:6])
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                check=True, text=True, env=env)
        return result.stdout
    except subprocess.CalledProcessError as e:
        stderr = e.stderr or ""
        if "locked" in stderr:
            log(f"SKIP {cmd_str}: repository is locked")
        else:
            log(f"ERROR {cmd_str}: {stderr.strip()}")
        return None


def export_snapshots(config):
    """Exports snapshot information from restic using JSON output."""
    command = ["restic", "-r", config['RESTIC_REPOSITORY'], "snapshots", "--json", "--no-lock"]
    env = get_restic_env(config)
    output = run_restic_command(command, env)

    if output is None:
        return []

    try:
        snapshots_json = json.loads(output)
    except json.JSONDecodeError as e:
        log(f"ERROR parsing snapshots JSON: {e}")
        return []

    snapshots = []
    for snap in snapshots_json:
        # Parse ISO 8601 timestamp
        time_str = snap.get("time", "")
        try:
            # Truncate sub-microsecond precision (restic uses nanoseconds),
            # since fromisoformat() only supports up to 6 decimal digits on Python < 3.11
            time_str = re.sub(r'(\.\d{6})\d+', r'\1', time_str.replace("Z", "+00:00"))
            dt = datetime.datetime.fromisoformat(time_str)
            timestamp = int(dt.timestamp())
        except (ValueError, AttributeError):
            timestamp = 0

        tags = ",".join(snap.get("tags", [])) if snap.get("tags") else "none"
        paths = ",".join(snap.get("paths", [])) if snap.get("paths") else "unknown"

        summary = snap.get("summary", {})
        size = summary.get("total_bytes_processed", 0) if summary else 0

        snapshots.append({
            "id": snap.get("short_id", "unknown"),
            "timestamp": timestamp,
            "hostname": snap.get("hostname", "unknown"),
            "tags": tags,
            "directory": paths,
            "size": size,
        })

    return snapshots


def export_stats(config):
    """Exports repository statistics from restic."""
    env = get_restic_env(config)

    # Get restore size (default mode)
    log("Fetching repo stats (restore-size mode)...")
    command_restore = ["restic", "-r", config['RESTIC_REPOSITORY'], "stats", "--json", "--no-lock"]
    output_restore = run_restic_command(command_restore, env)
    if output_restore:
        try:
            stats = json.loads(output_restore)
            restore_size = stats.get("total_size", 0)
            file_count = stats.get("total_file_count", 0)
            REPO_RESTORE_SIZE.set(restore_size)
            REPO_FILE_COUNT.set(file_count)
            log(f"  Restore size: {restore_size / (1024**3):.2f} GiB, Files: {file_count}")
        except json.JSONDecodeError as e:
            log(f"  ERROR parsing stats JSON: {e}")
    else:
        log("  No output from restic stats")

    # Get raw repo size on disk
    log("Fetching repo stats (raw-data mode)...")
    command_raw = ["restic", "-r", config['RESTIC_REPOSITORY'], "stats", "--json", "--no-lock", "--mode", "raw-data"]
    output_raw = run_restic_command(command_raw, env)
    if output_raw:
        try:
            stats_raw = json.loads(output_raw)
            raw_size = stats_raw.get("total_size", 0)
            REPO_RAW_SIZE.set(raw_size)
            log(f"  Raw repo size: {raw_size / (1024**3):.2f} GiB")
        except json.JSONDecodeError as e:
            log(f"  ERROR parsing raw stats JSON: {e}")
    else:
        log("  No output from restic stats --mode raw-data")



def export_locks(config):
    """Counts the number of active locks in the restic repository."""
    command = ["restic", "-r", config['RESTIC_REPOSITORY'], "list", "locks", "--no-lock"]
    env = get_restic_env(config)
    output = run_restic_command(command, env)

    if output is None:
        return

    lock_ids = [line.strip() for line in output.splitlines() if line.strip()]
    LOCKS_TOTAL.set(len(lock_ids))
    if lock_ids:
        log(f"  Locks: {len(lock_ids)} active")


def update_prometheus_metrics(config):
    """Fetches restic data and updates all Prometheus metrics."""
    log("--- Updating metrics ---")

    # --- Snapshots ---
    log("Fetching snapshots...")
    snapshots = export_snapshots(config)
    SNAPSHOT_COUNT.set(len(snapshots))
    log(f"  Found {len(snapshots)} snapshots")

    # Track latest timestamp and snapshot ID per (host, directory)
    latest_per_host_dir = {}

    for snapshot in snapshots:
        snapshot_id = snapshot["id"]
        timestamp = snapshot["timestamp"]
        host = snapshot["hostname"]
        tags = snapshot["tags"]
        directory = snapshot["directory"]

        SNAPSHOT_TIMESTAMP.labels(
            host=host,
            id=snapshot_id,
            date=str(timestamp),
            tags=tags,
            directory=directory
        ).set(timestamp)

        # Track latest snapshot per host/directory
        key = (host, directory)
        if key not in latest_per_host_dir or timestamp > latest_per_host_dir[key][0]:
            latest_per_host_dir[key] = (timestamp, snapshot["size"])

    # Set latest timestamp and size metrics
    for (host, directory), (timestamp, size) in latest_per_host_dir.items():
        SNAPSHOT_LATEST_TIMESTAMP.labels(host=host, directory=directory).set(timestamp)
        SNAPSHOT_LATEST_SIZE.labels(host=host, directory=directory).set(size)
        age_hours = (time.time() - timestamp) / 3600
        log(f"  Latest backup for {host}:{directory} — {age_hours:.1f} hours ago, {size / (1024**3):.2f} GiB")

    # --- Repository stats ---
    export_stats(config)

    # --- Locks ---
    log("Checking locks...")
    export_locks(config)

    log("--- Done ---\n")


def seconds_until(schedule_time, tz):
    """Returns seconds until the next occurrence of schedule_time in the given timezone."""
    now = datetime.datetime.now(tz)
    hour, minute = map(int, schedule_time.split(':'))
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return (target - now).total_seconds()


def main():
    config_file = sys.argv[1] if len(sys.argv) > 1 else None
    config = load_config(config_file)

    log(f"Repository: {config['RESTIC_REPOSITORY']}")

    schedule_time = config.get('SCHEDULE_TIME')
    tz = ZoneInfo(config['TIMEZONE'])

    if schedule_time:
        log(f"Scheduled to run daily at {schedule_time} ({config['TIMEZONE']})")
    else:
        log(f"Update interval: {config['UPDATE_INTERVAL']}s ({config['UPDATE_INTERVAL']//60}min)")

    start_http_server(config['EXPORTER_PORT'])
    log(f"Prometheus metrics server running on :{config['EXPORTER_PORT']}/metrics")

    # Always run once at startup
    update_prometheus_metrics(config)

    while True:
        if schedule_time:
            wait = seconds_until(schedule_time, tz)
            log(f"Next update at {schedule_time} ({config['TIMEZONE']}), sleeping {wait/3600:.1f}h")
            time.sleep(wait)
        else:
            time.sleep(config['UPDATE_INTERVAL'])
        update_prometheus_metrics(config)


if __name__ == "__main__":
    main()
