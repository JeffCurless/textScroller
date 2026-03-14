#!/usr/bin/env python3
"""
scheduler.py — Host-side scheduler for the Galactic Unicorn text display.

Usage:
    python3 scheduler.py [schedule.json]

Reads a JSON schedule config and a plain-text messages file, then runs
continuously, sending the configured message to the display device via HTTP
at the scheduled time each day.  The schedule resets automatically at midnight.

No third-party packages are required — only the Python standard library.
"""

import datetime
import http.client
import json
import os
import sys
import time

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# How often the main loop wakes up to check the clock.
# 30 seconds guarantees the scheduler checks at least twice within any given
# 60-second window, so no scheduled minute can be missed.
POLL_INTERVAL = 30

# Default config file name, used when no argument is given on the command line
DEFAULT_CONFIG = "schedule.json"


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log(msg):
    """Print a timestamped message to stdout.

    All output uses this function so every line carries a consistent
    ISO-style timestamp that makes it easy to correlate log entries with
    the schedule.
    """
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("[{}] {}".format(ts, msg))


# ---------------------------------------------------------------------------
# Config and message loading
# ---------------------------------------------------------------------------

def load_config(path):
    """Load and validate the JSON schedule config file.

    Checks that the file exists, is valid JSON, and contains the three
    required top-level keys.  Exits with a descriptive error on any problem
    so the operator sees a clear message rather than a Python traceback.

    Args:
        path (str): Path to the schedule.json file.

    Returns:
        dict: The parsed config object.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except FileNotFoundError:
        log("ERROR: Config file not found: {}".format(path))
        sys.exit(1)
    except json.JSONDecodeError as exc:
        log("ERROR: Config file is not valid JSON: {}".format(exc))
        sys.exit(1)

    # Validate required top-level keys
    for required in ("display_ip", "messages_file", "schedule"):
        if required not in cfg:
            log("ERROR: Config missing required key '{}'".format(required))
            sys.exit(1)

    if not isinstance(cfg["schedule"], list):
        log("ERROR: Config 'schedule' must be a JSON array")
        sys.exit(1)

    return cfg


def load_messages(messages_path):
    """Read the messages file and return a list of non-empty lines.

    Blank lines are silently skipped so the file can include spacing for
    readability without affecting line numbers.

    Args:
        messages_path (str): Absolute path to the messages text file.

    Returns:
        list[str]: Message strings, 0-indexed internally (schedule.json
                   references them with 1-based line numbers).
    """
    try:
        with open(messages_path, "r", encoding="utf-8") as fh:
            lines = [ln.rstrip("\n") for ln in fh if ln.strip()]
    except FileNotFoundError:
        log("ERROR: Messages file not found: {}".format(messages_path))
        sys.exit(1)

    if not lines:
        log("ERROR: Messages file is empty: {}".format(messages_path))
        sys.exit(1)

    return lines


# ---------------------------------------------------------------------------
# Schedule normalisation
# ---------------------------------------------------------------------------

def parse_time(raw):
    """Convert an "HH:MM" string to a (hour, minute) tuple.

    Args:
        raw (str): Time string in 24-hour HH:MM format.

    Returns:
        tuple[int, int] | None: (hour, minute), or None if the string is
        not a valid time.
    """
    try:
        parts = raw.split(":")
        if len(parts) != 2:
            return None
        hh, mm = int(parts[0]), int(parts[1])
        if not (0 <= hh <= 23 and 0 <= mm <= 59):
            return None
        return (hh, mm)
    except (ValueError, AttributeError):
        return None


def normalize_schedule(raw_schedule, messages):
    """Validate every schedule entry and resolve line numbers to message text.

    Each entry in schedule.json must have:
      "time"  — "HH:MM" string (24-hour)
      "line"  — 1-based integer index into the messages file
      "color" — optional [R, G, B] list (integers 0–255 each)

    Invalid color values produce a warning and are dropped (the display
    will use its own default color).  Any other invalid field causes the
    program to exit so misconfiguration is caught at startup rather than
    silently at runtime.

    Args:
        raw_schedule (list): The "schedule" array from the config file.
        messages (list[str]): Lines loaded from the messages file.

    Returns:
        list[dict]: Normalised entries with keys "hhmm", "text",
                    and optionally "color".
    """
    normalized = []
    for idx, entry in enumerate(raw_schedule):
        label = "schedule[{}]".format(idx)   # used in error messages

        # --- Validate and parse the time field ---
        raw_time = entry.get("time")
        if raw_time is None:
            log("ERROR: {} missing 'time' field".format(label))
            sys.exit(1)
        hhmm = parse_time(raw_time)
        if hhmm is None:
            log("ERROR: {} 'time' is not valid HH:MM: {!r}".format(label, raw_time))
            sys.exit(1)

        # --- Validate and resolve the line number ---
        raw_line = entry.get("line")
        if raw_line is None:
            log("ERROR: {} missing 'line' field".format(label))
            sys.exit(1)
        try:
            line_num = int(raw_line)
        except (TypeError, ValueError):
            log("ERROR: {} 'line' must be an integer".format(label))
            sys.exit(1)
        if line_num < 1 or line_num > len(messages):
            log("ERROR: {} 'line' {} is out of range (1–{})".format(
                label, line_num, len(messages)))
            sys.exit(1)
        # Convert from 1-based (user-facing) to 0-based (Python list index)
        text = messages[line_num - 1]

        # --- Validate the optional color field ---
        norm      = {"hhmm": hhmm, "text": text}
        raw_color = entry.get("color")
        if raw_color is not None:
            if (isinstance(raw_color, list) and len(raw_color) == 3
                    and all(isinstance(c, int) and 0 <= c <= 255
                            for c in raw_color)):
                norm["color"] = raw_color
            else:
                log("WARNING: {} 'color' must be [R, G, B] integers 0–255; "
                    "ignoring".format(label))

        normalized.append(norm)

    return normalized


# ---------------------------------------------------------------------------
# HTTP sender
# ---------------------------------------------------------------------------

def send_message(ip, port, text, color=None):
    """Send a single message to the display device via HTTP POST /message.

    Builds a JSON payload matching the display's API contract and posts it
    using http.client (standard library only, no third-party dependencies).

    resp.read() is called before conn.close() to drain the response body.
    This prevents a broken-pipe exception on the Pico W's asyncio server,
    which calls writer.drain() before closing its end of the connection.

    Args:
        ip    (str):        IP address of the display device.
        port  (int):        HTTP port (normally 80).
        text  (str):        Message text to display.
        color (list|None):  Optional [R, G, B] color list; omitted if None
                            so the display uses its own DEFAULT_COLOR.

    Returns:
        True on HTTP 200, or an error string describing the failure.
    """
    payload = {"text": text}
    if color is not None:
        payload["color"] = color

    body = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        # http.client adds Content-Length automatically from the body bytes;
        # we omit it here to avoid sending a duplicate header.
    }
    try:
        conn = http.client.HTTPConnection(ip, port, timeout=10)
        conn.request("POST", "/message", body=body, headers=headers)
        resp = conn.getresponse()
        resp.read()     # drain response body before closing
        conn.close()
        if resp.status == 200:
            return True
        return "HTTP {}".format(resp.status)
    except OSError as exc:
        return f"Network error: {exc}"
    except Exception as exc:
        return f"Unexpected error: {exc}"


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def run(config_path):
    """Load config and run the scheduler loop indefinitely.

    Startup steps:
      1. Parse and validate schedule.json.
      2. Load and validate messages.txt.
      3. Normalise the schedule (resolve line numbers → message text).
      4. Poll the system clock every POLL_INTERVAL seconds.
         - When (hour, minute) matches a schedule entry not yet sent today,
           POST the message to the display.
         - Track sent entries by index so each fires at most once per day.
         - Reset the tracking set at midnight for the next day's schedule.

    On network failure the error is logged and the entry remains eligible
    for retry on the next poll (still within the same minute window).

    Args:
        config_path (str): Path to the schedule.json config file.
    """
    log("Loading config: {}".format(config_path))
    cfg = load_config(config_path)

    ip   = cfg["display_ip"]
    port = int(cfg.get("display_port", 80))

    # Resolve the messages file path relative to the config file's directory.
    # This ensures the scheduler works correctly no matter what the current
    # working directory is (important when run from cron or systemd).
    config_dir    = os.path.dirname(os.path.abspath(config_path))
    messages_path = os.path.join(config_dir, cfg["messages_file"])

    log("Loading messages: {}".format(messages_path))
    messages = load_messages(messages_path)
    log("Loaded {} message(s)".format(len(messages)))

    schedule = normalize_schedule(cfg["schedule"], messages)
    log("Schedule: {} entr{}".format(
        len(schedule), "y" if len(schedule) == 1 else "ies"))
    log("Target: http://{}:{}/message".format(ip, port))
    log("Polling every {}s. Press Ctrl-C to stop.".format(POLL_INTERVAL))

    # sent_today holds the integer index of every schedule entry that has
    # already been dispatched today, preventing double-sends within a minute.
    sent_today = set()
    last_date  = datetime.date.today()

    while True:
        now   = datetime.datetime.now()
        today = now.date()

        # At midnight, clear the sent set so the schedule repeats for the new day
        if today != last_date:
            log("New day {}. Resetting schedule.".format(today.isoformat()))
            sent_today.clear()
            last_date = today

        current_hhmm = (now.hour, now.minute)

        for i, entry in enumerate(schedule):
            # Fire if the current minute matches and we haven't sent it yet today
            if entry["hhmm"] == current_hhmm and i not in sent_today:
                text  = entry["text"]
                color = entry.get("color")   # None if not specified
                result = send_message(ip, port, text, color)
                if result is True:
                    sent_today.add(i)        # mark as sent for today
                    log("Sent entry {} at {:02d}:{:02d}: {!r}{}".format(
                        i + 1, *entry["hhmm"], text,
                        "  color={}".format(color) if color else ""))
                else:
                    # Log the error but do NOT add to sent_today — the next
                    # poll (within 30 s, still in the same minute) will retry.
                    log("ERROR on entry {} at {:02d}:{:02d}: {}".format(
                        i + 1, *entry["hhmm"], result))

        time.sleep(POLL_INTERVAL)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Accept an optional positional argument for the config file path;
    # default to schedule.json in the current directory.
    config_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CONFIG
    try:
        run(config_path)
    except KeyboardInterrupt:
        log("Scheduler stopped.")
