# display.py — Async scroll animation loop and hardware button handling.
#
# run_display() is one of the two long-running coroutines started by main.py.
# Each iteration of its loop:
#   1. Checks the four hardware buttons (with debounce).
#   2. If not paused, clears the framebuffer, draws the current message at
#      the current horizontal position, pushes the frame to the LEDs, then
#      advances the scroll position by one pixel.
#   3. Yields control to the event loop via asyncio.sleep_ms(), giving the
#      HTTP server coroutine a chance to run.

try:
    import asyncio
except ImportError:
    import uasyncio as asyncio

import time
from galactic import GalacticUnicorn
from config import TEXT_Y_OFFSET, TEXT_SCALE, SCROLL_PADDING


async def run_display(state, gu, graphics):
    """Scroll text across the display and handle hardware button input.

    Args:
        state:    Shared AppState instance (see state.py).
        gu:       GalacticUnicorn hardware instance.
        graphics: PicoGraphics framebuffer bound to the Galactic Unicorn display.
    """
    # Select the bitmap8 font — 8 px tall, which best fills the 11-pixel
    # display height when positioned at TEXT_Y_OFFSET = 0.
    graphics.set_font("bitmap8")

    last_button_time = 0   # timestamp of the last accepted button press (ms)
    DEBOUNCE_MS = 200      # ignore further presses within this window to prevent
                           # a single physical press registering multiple times

    while True:
        now = time.ticks_ms()  # current time in milliseconds (wraps after ~49 days)

        # --- Button polling ---
        # ticks_diff() handles the millisecond counter wrap correctly.
        if time.ticks_diff(now, last_button_time) > DEBOUNCE_MS:
            if gu.is_pressed(GalacticUnicorn.SWITCH_A):
                # Button A — increase brightness by 10 %, capped at 1.0
                state.brightness = min(1.0, state.brightness + 0.1)
                gu.set_brightness(state.brightness)
                last_button_time = now
            elif gu.is_pressed(GalacticUnicorn.SWITCH_B):
                # Button B — decrease brightness by 10 %, floored at 0.0
                state.brightness = max(0.0, state.brightness - 0.1)
                gu.set_brightness(state.brightness)
                last_button_time = now
            elif gu.is_pressed(GalacticUnicorn.SWITCH_C):
                # Button C — toggle pause; when paused the display freezes
                state.paused = not state.paused
                last_button_time = now
            elif gu.is_pressed(GalacticUnicorn.SWITCH_D):
                # Button D — skip the current message and load the next one
                _advance_queue(state)
                last_button_time = now

        # --- Rendering ---
        if not state.paused:
            msg   = state.current_message
            text  = msg["text"]
            color = msg["color"]

            # Clear to black, then draw the text at the current scroll position
            graphics.set_pen(graphics.create_pen(0, 0, 0))
            graphics.clear()
            graphics.set_pen(graphics.create_pen(*color))
            # Arguments: text, x, y, word-wrap width (-1 = no wrap), scale
            graphics.text(text, state.scroll_x, TEXT_Y_OFFSET, -1, scale=TEXT_SCALE)
            gu.update(graphics)  # push framebuffer to the physical LEDs

            # Measure rendered width so we know when the text has fully scrolled off
            text_width = graphics.measure_text(text, scale=TEXT_SCALE)
            state.scroll_x -= 1  # advance one pixel to the left each tick

            # When the trailing edge of the text plus the padding gap has passed
            # the left edge of the display, move on to the next queued message
            if state.scroll_x < -(text_width + SCROLL_PADDING):
                _advance_queue(state)

        # Yield to the event loop for the configured scroll speed interval.
        # This is the main cooperative yield point — the HTTP server coroutine
        # gets CPU time here while the display waits for the next tick.
        await asyncio.sleep_ms(state.scroll_speed_ms)


def _advance_queue(state):
    """Load the next message from the queue, or loop back to the default.

    If the message queue is non-empty, pop the oldest entry and make it the
    current message.  If the queue is empty the current message is left
    unchanged (it will scroll again from the right).  Either way, reset
    scroll_x so the next message enters from the right edge of the display.
    """
    if state.message_queue:
        state.current_message = state.message_queue.pop(0)  # FIFO
    state.scroll_x = 53  # restart from just off the right edge (display width)
