# Galactic Unicorn Text Scroller

A MicroPython application for the [Pimoroni Galactic Unicorn](https://shop.pimoroni.com/products/galactic-unicorn) (Raspberry Pi Pico W) that scrolls text across its 53×11 LED matrix display and exposes an HTTP API so messages can be pushed remotely.

A companion host-side scheduler (`host/scheduler.py`) reads messages from a file and sends them to the display at configured times each day.

## Features

- Scrolls a queue of messages across the display
- Full-color text (per-message RGB)
- Adjustable brightness and scroll speed
- Pause/resume and skip controls via hardware buttons
- HTTP JSON API for remote control
- Host scheduler: time-based message delivery from a config file

---

## Project Structure

```
textScroller/
└── Pico
    ├── main.py         — Entry point: boot sequence, WiFi, starts display + server tasks
    ├── config.py       — All tunable constants (WiFi credentials, display settings)
    ├── state.py        — Shared AppState singleton used by display and server
    ├── wifi.py         — Blocking WiFi connect; returns IP or raises RuntimeError
    ├── display.py      — Async scroll animation loop and hardware button handling
    ├── server.py       — Async HTTP server: request parsing and route dispatch
└── host/
    ├── scheduler.py  — Host-side scheduler: sends messages at configured times
    ├── schedule.json — Schedule config: display IP, times, message line references
    └── messages.txt  — One message per line; referenced by line number in schedule.json
```

---

## Pico W Setup

### 1. Configure WiFi

Edit `config.py` and set your network credentials:

```python
WIFI_SSID     = "your_network_name"
WIFI_PASSWORD = "your_password"
```

### 2. Deploy to the Pico W

Copy all root-level `.py` files to the device. Using `mpremote`:

```bash
mpremote cp main.py config.py state.py wifi.py display.py server.py :
```

Or use Thonny — open each file and use **File → Save as… → Raspberry Pi Pico**.

### 3. Power on

The display will show:
1. `Connecting...` — while joining WiFi
2. The assigned IP address in green for 2 seconds — or `WiFi FAIL` in red if the connection times out
3. The default `Galactic Unicorn` message begins scrolling

---

## Hardware Buttons

| Button | Action |
|--------|--------|
| **A** | Brightness up (+10%) |
| **B** | Brightness down (−10%) |
| **C** | Toggle pause / resume |
| **D** | Skip to next queued message |

---

## HTTP API

All endpoints are on port 80. Responses are JSON. Replace `<IP>` with the address shown on boot.

---

### POST /message

Queue a message to display. `text` is required; `color` is optional (defaults to white).

```bash
curl -X POST http://<IP>/message \
     -H "Content-Type: application/json" \
     -d '{"text": "Hello World"}'
```

With a custom color (RGB 0–255):

```bash
curl -X POST http://<IP>/message \
     -H "Content-Type: application/json" \
     -d '{"text": "Alert!", "color": [255, 0, 0]}'
```

Response:

```json
{"status": "ok", "queued": 1}
```

Error responses:

| HTTP | Body | Meaning |
|------|------|---------|
| 400 | `{"error": "missing 'text' field"}` | `text` key absent from request body |
| 429 | `{"error": "queue full"}` | 10 messages already queued |

---

### GET /status

Returns the current display state.

```bash
curl http://<IP>/status
```

Response:

```json
{
  "current":    "Hello World",
  "queued":     2,
  "paused":     false,
  "brightness": 0.5,
  "ip":         "192.168.1.82"
}
```

---

### POST /settings

Adjust brightness, scroll speed, or pause state at runtime. All fields are optional — send only what you want to change.

```bash
# Set brightness to 80%
curl -X POST http://<IP>/settings \
     -H "Content-Type: application/json" \
     -d '{"brightness": 0.8}'

# Slow the scroll (ms per pixel; higher = slower)
curl -X POST http://<IP>/settings \
     -H "Content-Type: application/json" \
     -d '{"speed": 80}'

# Pause the display
curl -X POST http://<IP>/settings \
     -H "Content-Type: application/json" \
     -d '{"pause": true}'

# Multiple settings at once
curl -X POST http://<IP>/settings \
     -H "Content-Type: application/json" \
     -d '{"brightness": 0.6, "speed": 40, "pause": false}'
```

Response:

```json
{"status": "ok"}
```

---

### POST /clear

Clears the queue, stops the current message, and resets to the default `Galactic Unicorn` message.

```bash
curl -X POST http://<IP>/clear
```

Response:

```json
{"status": "ok"}
```

---

## Host Scheduler

`host/scheduler.py` runs on any Python 3 host machine. It reads a messages file and a schedule config, then sends the right message to the display at the right time each day. No third-party packages are required.

### messages.txt

One message per line. Blank lines are ignored. Line numbers are 1-based, matching the `"line"` field in `schedule.json`.

```
Good morning! Have a great day.
Stand-up meeting in 30 minutes.
Lunchtime! Take a proper break.
Wrapping up for the day. Great work!
Why are Operating Systems special?
```

### schedule.json

```json
{
  "display_ip":    "192.168.1.82",
  "display_port":  80,
  "messages_file": "messages.txt",
  "schedule": [
    { "time": "20:17", "line": 1 },
    { "time": "20:20", "line": 2, "color": [255, 200, 0] },
    { "time": "20:22", "line": 3, "color": [0, 200, 255] },
    { "time": "20:25", "line": 4 },
    { "time": "20:30", "line": 5, "color": [255, 80, 80] }
  ]
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `display_ip` | Yes | IP address shown on the display at boot |
| `display_port` | No | HTTP port (default: `80`) |
| `messages_file` | Yes | Path to messages file, relative to `schedule.json` |
| `schedule[].time` | Yes | Send time in `HH:MM` 24-hour format |
| `schedule[].line` | Yes | 1-based line number from `messages.txt` |
| `schedule[].color` | No | RGB color `[R, G, B]` (0–255 each); omit to use the display's default |

### Running the Scheduler

```bash
# From the host/ directory — uses schedule.json by default
python3 scheduler.py

# With an explicit config path
python3 scheduler.py /path/to/my-schedule.json
```

Sample output:

```
[2026-03-13 20:16:50] Loading config: schedule.json
[2026-03-13 20:16:50] Loading messages: /home/user/textScroller/host/messages.txt
[2026-03-13 20:16:50] Loaded 5 message(s)
[2026-03-13 20:16:50] Schedule: 5 entries
[2026-03-13 20:16:50] Target: http://192.168.1.82:80/message
[2026-03-13 20:16:50] Polling every 30s. Press Ctrl-C to stop.
[2026-03-13 20:17:02] Sent entry 1 at 20:17: 'Good morning! Have a great day.'
[2026-03-13 20:20:15] Sent entry 2 at 20:20: 'Stand-up meeting in 30 minutes.'  color=[255, 200, 0]
```

Press **Ctrl-C** to stop. The schedule resets automatically at midnight each day.

### Running as a Background Process

```bash
# Start in the background, log to file
nohup python3 scheduler.py > scheduler.log 2>&1 &
echo $! > scheduler.pid

# Stop it later
kill $(cat scheduler.pid)
```

---

## Pico W Configuration Reference

All defaults live in `config.py`:

| Constant | Default | Description |
|----------|---------|-------------|
| `WIFI_SSID` | `""` | WiFi network name |
| `WIFI_PASSWORD` | `""` | WiFi password |
| `WIFI_TIMEOUT` | `20` | Seconds before connect gives up |
| `DEFAULT_SCROLL_SPEED` | `50` | Milliseconds per pixel (lower = faster) |
| `DEFAULT_BRIGHTNESS` | `0.5` | Initial brightness (0.0–1.0) |
| `DEFAULT_COLOR` | `(255,255,255)` | Default text color (white) |
| `TEXT_Y_OFFSET` | `0` | Vertical pixel offset for text (0 = top row) |
| `SCROLL_PADDING` | `10` | Blank pixels appended after each message |
| `HTTP_PORT` | `80` | HTTP server port |
| `MAX_QUEUE_DEPTH` | `10` | Maximum queued messages |
