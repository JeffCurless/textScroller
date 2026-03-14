# state.py — Shared application state for the Galactic Unicorn text scroller.
#
# A single AppState instance is created at module level and imported by both
# display.py and server.py.  Because MicroPython's uasyncio is cooperative
# (not preemptive), both tasks share this object safely without locks —
# only one coroutine runs at a time, so list and attribute mutations are atomic
# from the perspective of the two tasks.

from config import DEFAULT_COLOR, DEFAULT_BRIGHTNESS, DEFAULT_SCROLL_SPEED


class AppState:
    def __init__(self):
        # Queue of pending messages sent via the HTTP API.
        # Each entry is a dict: {"text": str, "color": (R, G, B)}
        self.message_queue = []

        # The message currently being scrolled across the display.
        self.current_message = {"text": "Galactic Unicorn", "color": DEFAULT_COLOR}

        # Horizontal pixel position of the left edge of the text.
        # Starts at 53 (just off the right edge of the 53-pixel-wide display)
        # and decrements by 1 each tick, scrolling the text leftward.
        self.scroll_x = 53

        # When True the display loop skips rendering and the text freezes.
        # Toggled by hardware button C or the POST /settings API.
        self.paused = False

        # Current LED brightness (0.0–1.0).  Updated by buttons A/B and
        # POST /settings; mirrored to the hardware via gu.set_brightness().
        self.brightness = DEFAULT_BRIGHTNESS

        # Delay in milliseconds between each one-pixel scroll step.
        # Larger values slow the scroll.  Minimum enforced at 10 ms by the API.
        self.scroll_speed_ms = DEFAULT_SCROLL_SPEED

        # IP address assigned by DHCP after WiFi connects, stored so the
        # GET /status endpoint can report it back to callers.
        self.ip_address = None


# Module-level singleton imported everywhere state is needed.
state = AppState()
