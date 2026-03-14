# config.py — Tunable constants for the Galactic Unicorn text scroller.
#
# Edit this file before deploying to the Pico W.  All other modules import
# from here so there is a single place to change any setting.

# ---------------------------------------------------------------------------
# WiFi credentials
# ---------------------------------------------------------------------------

WIFI_SSID     = "SSID"
WIFI_PASSWORD = "PASSWORD"
WIFI_TIMEOUT  = 20          # seconds to wait for a connection before giving up

# ---------------------------------------------------------------------------
# Display defaults
# ---------------------------------------------------------------------------

DEFAULT_SCROLL_SPEED = 50   # milliseconds between each one-pixel scroll step;
                            # lower values scroll faster
DEFAULT_BRIGHTNESS   = 0.5  # initial LED brightness (0.0 = off, 1.0 = full)
DEFAULT_COLOR        = (255, 255, 255)  # default text color as (R, G, B)

TEXT_SCALE    = 1           # font scale factor passed to PicoGraphics.text()
TEXT_Y_OFFSET = 0           # vertical pixel offset; 0 starts text at the top row
SCROLL_PADDING = 10         # blank pixels appended after a message before the
                            # next one begins, giving a visual gap between messages

# ---------------------------------------------------------------------------
# HTTP server
# ---------------------------------------------------------------------------

HTTP_PORT       = 80        # port the built-in web server listens on
HTTP_HOST       = "0.0.0.0" # bind address; 0.0.0.0 accepts connections on all interfaces
MAX_QUEUE_DEPTH = 10        # maximum number of messages that can be queued at once;
                            # POST /message returns 429 when this limit is reached
